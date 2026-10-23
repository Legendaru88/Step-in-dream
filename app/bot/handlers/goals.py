from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.photo_hints import offer_photo_report
from app.bot.keyboards.inline import goal_delete_confirm_keyboard, goal_details_keyboard, goals_list_keyboard
from app.models.goal import Goal, GoalStatus
from app.models.step import Step, StepStatus
from app.services.llm import OpenRouterClient, OpenRouterError
from app.services.progress import refresh_goal_status
from app.utils.db import get_goal_for_user, get_or_create_user, get_user_goals
from app.utils.formatters import format_goal_details

router = Router()
llm_client = OpenRouterClient()


def _extract_id(data: str) -> int | None:
    try:
        return int(data.rsplit("_", 1)[-1])
    except (ValueError, TypeError):
        return None


@router.message(Command("goals"))
@router.message(F.text == "🎯 Мои цели")
async def list_goals(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return

    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    goals = await get_user_goals(session, user.id)
    await session.commit()

    if not goals:
        await message.answer("У тебя пока нет целей. Нажми «➕ Новая цель».")
        return

    await message.answer("Твои цели:", reply_markup=goals_list_keyboard(goals))


@router.callback_query(F.data.startswith("goal_view_"))
async def view_goal(callback: CallbackQuery, session: AsyncSession, state: FSMContext | None = None) -> None:
    if callback.from_user is None:
        return

    goal_id = _extract_id(callback.data)
    if goal_id is None:
        await callback.answer("Некорректная цель")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    goal = await get_goal_for_user(session, user.id, goal_id)
    await session.commit()

    if goal is None:
        await callback.answer("Цель не найдена")
        return

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(format_goal_details(goal), reply_markup=goal_details_keyboard(goal))
        await offer_photo_report(callback.message, session, user.id, goal_id=goal.id, state=state)


@router.callback_query(F.data.startswith("step_done_"))
async def toggle_step(callback: CallbackQuery, session: AsyncSession, state: FSMContext | None = None) -> None:
    if callback.from_user is None:
        return

    step_id = _extract_id(callback.data)
    if step_id is None:
        await callback.answer("Некорректный шаг")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    step = await session.scalar(
        select(Step)
        .join(Goal, Goal.id == Step.goal_id)
        .where(Step.id == step_id, Goal.user_id == user.id)
    )
    if step is None:
        await callback.answer("Шаг не найден")
        return

    goal = await get_goal_for_user(session, user.id, step.goal_id)
    if goal is None:
        await callback.answer("Цель не найдена")
        return

    was_completed = goal.status == GoalStatus.COMPLETED

    if step.status == StepStatus.DONE:
        step.status = StepStatus.PENDING
        step.completed_at = None
    else:
        step.status = StepStatus.DONE
        step.completed_at = datetime.now(timezone.utc)

    await session.flush()
    goal = await get_goal_for_user(session, user.id, step.goal_id)
    if goal is None:
        await callback.answer("Цель не найдена")
        return
    refresh_goal_status(goal, goal.steps)

    congrats_text = None
    if not was_completed and goal.status == GoalStatus.COMPLETED:
        try:
            congrats_text = await llm_client.congratulate(goal.title)
        except OpenRouterError:
            congrats_text = f"Поздравляю! Цель «{goal.title}» выполнена!"

    await session.commit()

    await callback.answer("Обновлено")
    if callback.message is None:
        return

    text = format_goal_details(goal)
    if congrats_text:
        text = f"{congrats_text}\n\n{text}"

    await callback.message.edit_text(text, reply_markup=goal_details_keyboard(goal))
    await offer_photo_report(callback.message, session, user.id, goal_id=goal.id, state=state)


@router.callback_query(F.data.regexp(r"^goal_delete_\d+$"))
async def ask_delete_goal(callback: CallbackQuery) -> None:
    goal_id = _extract_id(callback.data)
    if goal_id is None:
        return

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Удалить эту цель?",
            reply_markup=goal_delete_confirm_keyboard(goal_id),
        )


@router.callback_query(F.data.startswith("goal_delete_confirm_"))
async def delete_goal(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return

    goal_id = _extract_id(callback.data)
    if goal_id is None:
        await callback.answer("Некорректная цель")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    goal = await get_goal_for_user(session, user.id, goal_id)
    if goal is None:
        await callback.answer("Цель не найдена")
        return

    await session.delete(goal)
    await session.commit()
    await callback.answer("Цель удалена")
    if callback.message:
        await callback.message.edit_text("Цель удалена.")


@router.callback_query(F.data.startswith("goal_delete_cancel_"))
async def cancel_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return

    goal_id = _extract_id(callback.data)
    if goal_id is None:
        await callback.answer("Некорректная цель")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    goal = await get_goal_for_user(session, user.id, goal_id)
    await session.commit()

    if goal is None:
        await callback.answer("Цель не найдена")
        return

    await callback.answer("Отменено")
    if callback.message:
        await callback.message.edit_text(format_goal_details(goal), reply_markup=goal_details_keyboard(goal))
