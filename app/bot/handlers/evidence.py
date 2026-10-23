import asyncio
import io
import json
import secrets
import time
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.dialog import DialogRole
from app.models.goal import GoalStatus
from app.models.step import StepStatus
from app.services.evidence import assess_image, prepare_image
from app.services.llm import OpenRouterClient, OpenRouterError
from app.services.progress import refresh_goal_status
from app.utils.db import add_dialog_log, get_goal_for_user, get_or_create_user, get_recent_dialog_logs, get_user_goals
from app.bot.keyboards.inline import goal_details_keyboard
from app.utils.formatters import format_goal_details

router = Router()
client = OpenRouterClient()


@router.message(F.photo | F.document)
async def image_evidence(message: Message, session: AsyncSession, state: FSMContext):
    if message.from_user is None:
        return
    if await state.get_state() is not None:
        await message.answer("Сначала закончи создание цели или нажми /start, затем пришли фото ещё раз.")
        return
    settings = get_settings()
    media = message.photo[-1] if message.photo else message.document
    if not media:
        return
    if message.document and message.document.mime_type not in {"image/jpeg", "image/png"}:
        await message.answer("Пришли фото или файл JPG/PNG. PDF и другие документы пока не поддерживаются.")
        return
    if media.file_size and media.file_size > settings.image_max_bytes:
        await message.answer("Картинка слишком большая. Пришли JPG/PNG до 8 МБ.")
        return
    data = await state.get_data()
    if time.time() - data.get("last_image_at", 0) < 15:
        await message.answer("Подожди немного перед следующей картинкой.")
        return
    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    goals = await get_user_goals(session, user.id)
    candidates = [{"id": g.id, "title": g.title, "steps": [
        {"id": s.id, "title": s.title, "description": s.description}
        for s in g.steps if s.status == StepStatus.PENDING
    ]} for g in goals if g.status == GoalStatus.ACTIVE]
    candidates = [g for g in candidates if g["steps"]]
    if not candidates:
        await session.commit()
        await message.answer("Пока нет незавершённых шагов. Сначала создай цель через /new.")
        return
    history = await get_recent_dialog_logs(session, user.id, limit=6)
    context = {"goals": candidates, "caption": (message.caption or "")[:2000],
               "history": [{"role": log.role.value, "text": log.content[:1000]} for log in history]}
    # Avoid keeping a database transaction open during external calls.
    user_id = user.id
    await session.commit()
    await state.update_data(pending_evidence=None, last_image_at=time.time())
    await message.answer("Смотрю изображение и сопоставляю его с твоими шагами…")
    try:
        file = await message.bot.get_file(media.file_id)
        if file.file_size and file.file_size > settings.image_max_bytes:
            raise ValueError("Картинка слишком большая. Максимум 8 МБ.")
        buffer = io.BytesIO()
        await message.bot.download_file(file.file_path, destination=buffer, timeout=25)
        image_url = await asyncio.to_thread(prepare_image, buffer.getvalue(), settings.image_max_bytes)
        decision = await assess_image(client, image_url, context)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    except (OpenRouterError, TelegramAPIError, TimeoutError, OSError):
        await message.answer("Не удалось проверить изображение. Попробуй позже. Прогресс не изменён.")
        return
    goal_id = next((g["id"] for g in candidates if any(s["id"] == decision.step_id for s in g["steps"])), None)
    record = {"type": "image_evidence", "file_unique_id": media.file_unique_id,
              "caption": message.caption or "", "mode": settings.image_analysis_mode,
              "model": settings.openrouter_model, "vision_model": settings.vision_model if settings.image_analysis_mode == "split" else None,
              **decision.model_dump()}
    await add_dialog_log(session, user_id, DialogRole.USER,
                         "[Изображение] " + (message.caption or "Без подписи"), goal_id=goal_id)
    await add_dialog_log(session, user_id, DialogRole.ASSISTANT,
                         json.dumps(record, ensure_ascii=False), goal_id=goal_id)
    await session.commit()
    labels = {"sufficient": "Можно использовать как подтверждение", "insufficient": "Пока недостаточно для зачёта",
              "uncertain": "Нужно уточнение", "unrelated": "Не вижу связи с текущими шагами"}
    keyboard = None
    if decision.verdict == "sufficient":
        token = secrets.token_hex(8)
        await state.update_data(pending_evidence={"token": token, "goal_id": goal_id,
            "step_id": decision.step_id, "expires": time.time() + 1800})
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="✅ Засчитать шаг", callback_data="evidence_accept_" + token)]])
    step_name = next((s["title"] for g in candidates for s in g["steps"] if s["id"] == decision.step_id), None)
    text = labels[decision.verdict] + "\n\n" + decision.observation[:1400] + "\n\n" + decision.reason[:1300]
    if step_name:
        text += "\n\nШаг: " + step_name[:255]
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("evidence_accept_"))
async def accept_evidence(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    pending = (await state.get_data()).get("pending_evidence")
    token = (callback.data or "").removeprefix("evidence_accept_")
    if not pending or pending["token"] != token or pending["expires"] < time.time():
        await callback.answer("Подтверждение устарело. Пришли картинку снова.", show_alert=True)
        return
    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    goal = await get_goal_for_user(session, user.id, pending["goal_id"])
    step = next((s for s in goal.steps if s.id == pending["step_id"]), None) if goal else None
    if step is None or goal.status != GoalStatus.ACTIVE or step.status != StepStatus.PENDING:
        await state.update_data(pending_evidence=None)
        await callback.answer("Шаг уже изменён или недоступен.", show_alert=True)
        return
    step.status = StepStatus.DONE
    step.completed_at = datetime.now(timezone.utc)
    refresh_goal_status(goal, goal.steps)
    await add_dialog_log(session, user.id, DialogRole.USER,
        "Подтверждён зачёт по изображению: шаг " + str(step.id), goal_id=goal.id)
    await session.commit()
    await state.update_data(pending_evidence=None)
    await callback.answer("Шаг засчитан")
    if callback.message:
        prefix = "Цель выполнена! Поздравляю!\n\n" if goal.status == GoalStatus.COMPLETED else "Шаг засчитан.\n\n"
        await callback.message.edit_text(prefix + format_goal_details(goal), reply_markup=goal_details_keyboard(goal))
