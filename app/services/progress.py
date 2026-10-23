from datetime import datetime, timezone
from typing import Sequence

from app.models.goal import Goal, GoalStatus
from app.models.step import Step, StepStatus


def calculate_progress(steps: Sequence[Step]) -> int:
    if not steps:
        return 0

    done_count = sum(1 for step in steps if step.status == StepStatus.DONE)
    return int(round((done_count / len(steps)) * 100))


def refresh_goal_status(goal: Goal, steps: Sequence[Step]) -> Goal:
    progress = calculate_progress(steps)
    goal.progress = progress

    if steps and all(step.status == StepStatus.DONE for step in steps):
        goal.status = GoalStatus.COMPLETED
        goal.completed_at = goal.completed_at or datetime.now(timezone.utc)
    elif goal.status == GoalStatus.COMPLETED:
        goal.status = GoalStatus.ACTIVE
        goal.completed_at = None

    return goal
