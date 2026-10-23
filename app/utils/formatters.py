from app.models.goal import Goal, GoalStatus
from app.models.step import StepStatus


def format_goal_details(goal: Goal) -> str:
    status_icon = "✅" if goal.status == GoalStatus.COMPLETED else "🎯"
    lines = [f"{status_icon} {goal.title}", f"Прогресс: {goal.progress}%"]

    for step in goal.steps:
        marker = "✅" if step.status == StepStatus.DONE else "⬜"
        lines.append(f"{marker} {step.title}")

    return "\n".join(lines)


def format_stats(stats: dict[str, int]) -> str:
    return (
        "📊 Статистика\n"
        f"Целей всего: {stats['total_goals']}\n"
        f"Завершено целей: {stats['completed_goals']}\n"
        f"Шагов выполнено: {stats['done_steps']} / {stats['total_steps']}"
    )
