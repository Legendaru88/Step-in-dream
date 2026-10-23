from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import goal_details_keyboard, goals_list_keyboard
from app.bot.keyboards.reply import main_menu_keyboard
from app.bot.states import GoalDialog
from app.bot.photo_hints import offer_photo_report, record_photo_preference
from app.models.dialog import DialogLog, DialogRole
from app.models.goal import Goal
from app.models.step import StepStatus
from app.services.llm import IntentName, OpenRouterClient, OpenRouterError
from app.utils.db import add_dialog_log, get_or_create_user, get_recent_dialog_logs, get_user_goals
from app.utils.formatters import format_goal_details

router = Router()
llm_client = OpenRouterClient()


async def _start_goal_dialog(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(GoalDialog.waiting_goal_input)
    await message.answer("Опиши цель в свободной форме. Я предложу план из этапов.")


async def _show_goals(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return

    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    goals = await get_user_goals(session, user.id)
    await session.commit()

    if not goals:
        await message.answer("У тебя пока нет целей. Нажми «➕ Новая цель».")
        return

    await message.answer("Твои цели:", reply_markup=goals_list_keyboard(goals))


async def _assist_progress_update(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return

    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    goals = await get_user_goals(session, user.id)
    await session.commit()

    if not goals:
        await message.answer("У тебя пока нет целей. Нажми «➕ Новая цель».")
        return

    if len(goals) == 1:
        goal = goals[0]
        await message.answer(
            "Нашёл одну цель. Нажми на нужный этап, чтобы отметить выполнение:\n\n" + format_goal_details(goal),
            reply_markup=goal_details_keyboard(goal),
        )
    else:
        await message.answer("Выбери цель, в которой хочешь отметить этап:", reply_markup=goals_list_keyboard(goals))
    # Multiple goals require explicit selection before suggesting a specific step.
    if len(goals) == 1:
        await offer_photo_report(message, session, user.id, user_message=message.text or "", goal_id=goals[0].id)


def _goals_context(goals: list[Goal]) -> str:
    if not goals:
        return "У пользователя пока нет активных целей."

    lines: list[str] = []
    for goal in goals:
        lines.append(f"- Цель: {goal.title} | статус: {goal.status.value} | прогресс: {goal.progress}%")
        for index, step in enumerate(goal.steps, start=1):
            marker = "done" if step.status == StepStatus.DONE else "pending"
            lines.append(f"  {index}. [{marker}] {step.title}")

    return "\n".join(lines)


def _dialog_history(logs: list[DialogLog]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for log in logs:
        content = log.content.strip()
        if not content or content.startswith("[photo_report:"):
            continue

        role = "assistant" if log.role == DialogRole.ASSISTANT else "user"
        history.append({"role": role, "content": content[:700]})

    return history[-6:]


async def _chat_with_user(message: Message, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    goals = await get_user_goals(session, user.id)
    history_logs = await get_recent_dialog_logs(session, user.id, limit=8)

    try:
        response = await llm_client.chat_in_goals_context(
            user_message=message.text,
            goals_context=_goals_context(goals),
            history=_dialog_history(history_logs),
        )
    except OpenRouterError:
        await session.commit()
        await message.answer("Сервис ИИ временно недоступен. Попробуй чуть позже.")
        return

    await add_dialog_log(session, user_id=user.id, role=DialogRole.USER, content=message.text)
    await add_dialog_log(session, user_id=user.id, role=DialogRole.ASSISTANT, content=response)
    await session.commit()

    await message.answer(response, reply_markup=main_menu_keyboard())
    if len(goals) == 1:
        await offer_photo_report(message, session, user.id, user_message=message.text, goal_id=goals[0].id)


@router.message(StateFilter(None), F.text)
async def smart_text_router(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    if message.from_user:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        if await record_photo_preference(session, user.id, text):
            await message.answer("Хорошо, больше не буду предлагать фотоотчёты. Этапы можно отмечать кнопками.")
            return

    try:
        intent: IntentName = await llm_client.classify_intent(text)
    except OpenRouterError:
        await message.answer(
            "Не удалось распознать запрос через ИИ. Попробуй снова или используй кнопки ниже.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if intent == "CREATE_GOAL":
        await _start_goal_dialog(message, state)
        return

    if intent == "LIST_GOALS":
        await _show_goals(message, session)
        return

    if intent == "UPDATE_PROGRESS":
        await _assist_progress_update(message, session)
        return

    if intent == "CHAT":
        await _chat_with_user(message, session)
        return

    await message.answer(
        "Не до конца понял запрос. Могу создать цель, показать цели, помочь отметить этап или просто ответить на вопрос.",
        reply_markup=main_menu_keyboard(),
    )
