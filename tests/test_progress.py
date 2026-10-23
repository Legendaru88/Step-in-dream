from app.models.goal import Goal, GoalStatus
from app.models.step import Step, StepStatus
from app.services.progress import calculate_progress, refresh_goal_status


def test_calculate_progress() -> None:
    steps = [
        Step(title="A", order=1, status=StepStatus.DONE, goal_id=1),
        Step(title="B", order=2, status=StepStatus.PENDING, goal_id=1),
        Step(title="C", order=3, status=StepStatus.DONE, goal_id=1),
    ]

    assert calculate_progress(steps) == 67


def test_refresh_goal_status_marks_completed() -> None:
    goal = Goal(user_id=1, title="Цель")
    steps = [
        Step(title="A", order=1, status=StepStatus.DONE, goal_id=1),
        Step(title="B", order=2, status=StepStatus.DONE, goal_id=1),
    ]

    refresh_goal_status(goal, steps)

    assert goal.progress == 100
    assert goal.status == GoalStatus.COMPLETED
    assert goal.completed_at is not None


def test_refresh_goal_status_reopens_goal() -> None:
    goal = Goal(user_id=1, title="Цель", status=GoalStatus.COMPLETED)
    steps = [
        Step(title="A", order=1, status=StepStatus.DONE, goal_id=1),
        Step(title="B", order=2, status=StepStatus.PENDING, goal_id=1),
    ]

    refresh_goal_status(goal, steps)

    assert goal.progress == 50
    assert goal.status == GoalStatus.ACTIVE
    assert goal.completed_at is None
