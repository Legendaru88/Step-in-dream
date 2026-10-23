from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import draft_goal_keyboard, goal_details_keyboard
from app.bot.states import GoalDialog
from app.bot.photo_hints import offer_photo_report, draft_photo_hint, record_photo_preference
from app.models.dialog import DialogRole
from app.models.goal import Goal
from app.models.step import Step, StepStatus
from app.services.goal_parser import GoalParserError, parse_goal_plan
from app.services.llm import OpenRouterClient, OpenRouterError
from app.services.progress import refresh_goal_status
from app.utils.db import add_dialog_log, get_or_create_user, get_goal_for_user
from app.utils.formatters import format_goal_details

router = Router()
llm_client = OpenRouterClient()


@router.message(Command("new"))
@router.message(F.text == "➕ Новая цель")
async def start_new_goal_dialog(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(GoalDialog.waiting_goal_input)
    await message.answer("Опиши цель в свободной форме. Я предложу план из этапов.")


@router.message(GoalDialog.waiting_goal_input, F.text)
async def process_goal_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None:
        return

    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)

    await record_photo_preference(session, user.id, message.text or "")

    try:
        llm_response = await llm_client.propose_goal_plan(message.text)
        goal_plan = parse_goal_plan(llm_response)
    except OpenRouterError:
        await message.answer("Не удалось получить ответ от LLM. Попробуй ещё раз чуть позже.")
        return
    except GoalParserError:
        await message.answer("Не смог разобрать план. Опиши цель чуть конкретнее и попробуй снова.")
        return

    await add_dialog_log(session, user_id=user.id, role=DialogRole.USER, content=message.text)
    await add_dialog_log(session, user_id=user.id, role=DialogRole.ASSISTANT, content=llm_response)
    await session.commit()

    await state.update_data(
        raw_goal_input=message.text,
        goal_title=goal_plan.title,
        goal_steps=goal_plan.steps,
        llm_response=llm_response,
    )
    await state.set_state(GoalDialog.waiting_goal_confirmation)

    lines = [
        "Отличная цель! Вот план:",
        f"ЦЕЛЬ: {goal_plan.title}",
        "ЭТАПЫ:",
    ]
    for idx, step in enumerate(goal_plan.steps, start=1):
        lines.append(f"{idx}. {step}")

    lines.append(await draft_photo_hint(
        session, user.id, llm_response, message.text or "", state))
    lines.append("\nСохранить эту цель?")
    await message.answer("\n".join(lines), reply_markup=draft_goal_keyboard())


@router.callback_query(GoalDialog.waiting_goal_confirmation, F.data == "draft_edit")
async def draft_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GoalDialog.waiting_goal_revision)
    await callback.answer()
    if callback.message:
        await callback.message.answer("Что изменить в плане? Напиши уточнение одним сообщением.")


@router.message(GoalDialog.waiting_goal_confirmation, F.text)
async def draft_text(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    if await record_photo_preference(session, user.id, message.text or ""):
        await message.answer("Хорошо, больше не буду предлагать фотоотчёты. План можно сохранить кнопкой ниже.",
                             reply_markup=draft_goal_keyboard())
    else:
        await message.answer("Чтобы уточнить план, нажми «Изменить»; чтобы продолжить — сохрани цель.",
                             reply_markup=draft_goal_keyboard())


@router.message(GoalDialog.waiting_goal_revision, F.text)
async def process_revision(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    await record_photo_preference(session, user.id, message.text or "")
    data = await state.get_data()
    raw_goal_input = data.get("raw_goal_input")
    if not raw_goal_input:
        await state.clear()
        await message.answer("Диалог устарел. Нажми /new и начни заново.")
        return

    try:
        llm_response = await llm_client.propose_goal_plan(raw_goal_input, revision_message=message.text)
        goal_plan = parse_goal_plan(llm_response)
    except OpenRouterError:
        await message.answer("LLM сейчас недоступен. Попробуй позже.")
        return
    except GoalParserError:
        await message.answer("Не смог обновить этапы. Попробуй переформулировать уточнение.")
        return

    await state.update_data(goal_title=goal_plan.title, goal_steps=goal_plan.steps, llm_response=llm_response)
    await state.set_state(GoalDialog.waiting_goal_confirmation)

    lines = [
        "Обновил план:",
        f"ЦЕЛЬ: {goal_plan.title}",
        "ЭТАПЫ:",
    ]
    for idx, step in enumerate(goal_plan.steps, start=1):
        lines.append(f"{idx}. {step}")

    lines.append(await draft_photo_hint(
        session, user.id, llm_response, message.text or "", state))
    lines.append("\nСохранить эту цель?")
    await message.answer("\n".join(lines), reply_markup=draft_goal_keyboard())


@router.callback_query(GoalDialog.waiting_goal_confirmation, F.data == "draft_cancel")
async def draft_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.answer("Создание цели отменено.")


@router.callback_query(GoalDialog.waiting_goal_confirmation, F.data == "draft_save")
async def draft_save(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None:
        return

    data = await state.get_data()
    goal_title = data.get("goal_title")
    goal_steps: list[str] = data.get("goal_steps") or []

    if not goal_title or not goal_steps:
        await callback.answer("Недостаточно данных")
        await state.clear()
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)

    goal = Goal(user_id=user.id, title=goal_title)
    session.add(goal)
    await session.flush()

    for index, step_title in enumerate(goal_steps, start=1):
        session.add(
            Step(
                goal_id=goal.id,
                title=step_title,
                order=index,
                status=StepStatus.PENDING,
            )
        )

    await session.flush()
    goal_with_steps = await get_goal_for_user(session, user.id, goal.id)
    if goal_with_steps is not None:
        refresh_goal_status(goal_with_steps, goal_with_steps.steps)

    await session.commit()
    goal = await get_goal_for_user(session, user.id, goal.id)
    await state.clear()

    await callback.answer("Цель сохранена")
    if goal is None:
        if callback.message:
            await callback.message.answer("Цель сохранена")
        return

    if callback.message:
        await callback.message.answer(
            "Цель сохранена! Отмечай этапы кнопками ниже.\n\n" + format_goal_details(goal),
            reply_markup=goal_details_keyboard(goal),
        )

        await offer_photo_report(
            callback.message, session, user.id,
            user_message="Пользователь только что сохранил новый план; выполнение ещё не началось.",
            goal_id=goal.id,
        )
