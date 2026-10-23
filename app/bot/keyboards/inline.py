from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.goal import Goal
from app.models.step import StepStatus


def draft_goal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data="draft_save"),
                InlineKeyboardButton(text="✏️ Изменить", callback_data="draft_edit"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="draft_cancel")],
        ]
    )


def goals_list_keyboard(goals: list[Goal]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for goal in goals:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{goal.title} ({goal.progress}%)",
                    callback_data=f"goal_view_{goal.id}",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def goal_details_keyboard(goal: Goal) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for step in goal.steps:
        marker = "✅" if step.status == StepStatus.DONE else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} {step.title}",
                    callback_data=f"step_done_{step.id}",
                )
            ]
        )

    rows.append(
        [InlineKeyboardButton(text="🗑 Удалить цель", callback_data=f"goal_delete_{goal.id}")]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def goal_delete_confirm_keyboard(goal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data=f"goal_delete_confirm_{goal_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"goal_delete_cancel_{goal_id}"),
            ]
        ]
    )
