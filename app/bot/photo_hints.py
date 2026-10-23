"""Optional photo discovery; durable opt-out and once-per-goal delivery."""
import logging
import re

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dialog import DialogLog, DialogRole
from app.models.goal import GoalStatus
from app.models.step import StepStatus
from app.services.llm import OpenRouterClient
from app.utils.db import add_dialog_log, get_recent_dialog_logs, get_goal_for_user
from app.utils.formatters import format_goal_details

logger = logging.getLogger(__name__)
DECLINED = "[photo_report:declined]"
OFFERED = "[photo_report:offered]"


def declines_photos(text: str) -> bool:
    text = text.lower().replace("ё", "е")
    photo = r"\b(?:фото\w*|сним\w*)"
    refusal = r"\b(?:не\s+(?:хочу|буду|надо|нужно|нужны|предлагай|присылай|прос[иь])|без\s+(?!обязатель)|отказываюсь\s+от)"
    return bool(re.search(refusal + r"[^.!?\n]{0,60}" + photo, text)
                or re.search(photo + r"[^.!?\n]{0,30}(?:не\s+(?:хочу|буду|надо|нужны|нужно))", text))


async def photo_declined(session: AsyncSession, user_id: int) -> bool:
    return bool(await session.scalar(select(DialogLog.id).where(
        DialogLog.user_id == user_id, DialogLog.content == DECLINED).limit(1)))


async def record_photo_preference(session: AsyncSession, user_id: int, text: str) -> bool:
    if declines_photos(text):
        if not await photo_declined(session, user_id):
            await add_dialog_log(session, user_id, DialogRole.USER, DECLINED)
        await session.commit()
        logger.info("photo_hint reason=declined")
        return True
    return False


async def draft_photo_hint(session: AsyncSession, user_id: int, context: str,
                           user_message: str, state: FSMContext) -> str:
    if await photo_declined(session, user_id):
        logger.info("photo_hint stage=draft reason=declined")
        return ""
    if (await state.get_data()).get("draft_photo_hint_shown"):
        logger.info("photo_hint stage=draft reason=already_offered")
        return ""
    await session.commit()
    hint = await OpenRouterClient().suggest_photo_report(context,
        "Это черновик. Лишь после сохранения цели и выполнения видимого шага можно прислать фото. "
        "Обязательно начни словами «После сохранения цели». " + user_message)
    if hint:
        await state.update_data(draft_photo_hint_shown=True)
        return "\n\nНеобязательный фотоотчёт (после сохранения цели): " + hint
    return ""


async def offer_photo_report(message: Message, session: AsyncSession, user_id: int,
                             user_message: str = "", goal_id: int | None = None,
                             state: FSMContext | None = None) -> bool:
    if state is not None and await state.get_state() is not None:
        logger.info("photo_hint reason=draft_in_progress")
        return False
    if await record_photo_preference(session, user_id, user_message) or await photo_declined(session, user_id):
        logger.info("photo_hint reason=declined")
        return False
    if goal_id is None:
        logger.info("photo_hint reason=no_goal")
        return False
    goal = await get_goal_for_user(session, user_id, goal_id)
    if goal is None or goal.status != GoalStatus.ACTIVE or not any(s.status == StepStatus.PENDING for s in goal.steps):
        logger.info("photo_hint reason=no_pending_steps")
        return False
    offered = await session.scalar(select(DialogLog.id).where(
        DialogLog.user_id == user_id, DialogLog.goal_id == goal_id,
        DialogLog.content == OFFERED).limit(1))
    if offered:
        logger.info("photo_hint reason=already_offered")
        return False
    logs = await get_recent_dialog_logs(session, user_id, limit=8)
    # Raw draft model responses were historically logged before rendering; they may
    # contain advice the parser never showed. Only delivered goal replies count.
    history = [{"role": log.role.value, "content": log.content[:1000]} for log in logs
               if log.role == DialogRole.USER or log.goal_id == goal_id]
    context = "Статус цели: " + goal.status.value + "\n" + format_goal_details(goal)
    context += "\nСтатусы шагов:\n" + "\n".join(
        f"{s.status.value}: {s.title}" for s in goal.steps)
    await session.commit()
    hint = await OpenRouterClient().suggest_photo_report(context, user_message, history)
    if hint:
        await message.answer("Необязательный фотоотчёт: " + hint)
        await add_dialog_log(session, user_id, DialogRole.ASSISTANT, hint, goal_id=goal_id)
        await add_dialog_log(session, user_id, DialogRole.ASSISTANT, OFFERED, goal_id=goal_id)
        await session.commit()
        logger.info("photo_hint reason=sent")
        return True
    return False
