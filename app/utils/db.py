from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dialog import DialogLog, DialogRole
from app.models.goal import Goal, GoalStatus
from app.models.step import Step, StepStatus
from app.models.user import User


async def get_or_create_user(session: AsyncSession, telegram_id: int, username: str | None) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        if username != user.username:
            user.username = username
            await session.flush()
        return user

    user = User(telegram_id=telegram_id, username=username)
    session.add(user)
    await session.flush()
    return user


async def get_user_goals(session: AsyncSession, user_id: int) -> list[Goal]:
    result = await session.scalars(
        select(Goal)
        .where(Goal.user_id == user_id)
        .options(selectinload(Goal.steps))
        .order_by(Goal.created_at.desc())
    )
    return list(result)


async def get_goal_for_user(session: AsyncSession, user_id: int, goal_id: int) -> Goal | None:
    return await session.scalar(
        select(Goal)
        .where(Goal.user_id == user_id, Goal.id == goal_id)
        .options(selectinload(Goal.steps))
    )


async def add_dialog_log(
    session: AsyncSession,
    user_id: int,
    role: DialogRole,
    content: str,
    goal_id: int | None = None,
) -> DialogLog:
    log = DialogLog(user_id=user_id, goal_id=goal_id, role=role, content=content)
    session.add(log)
    await session.flush()
    return log


async def get_recent_dialog_logs(session: AsyncSession, user_id: int, limit: int = 6) -> list[DialogLog]:
    result = await session.scalars(
        select(DialogLog)
        .where(DialogLog.user_id == user_id)
        .order_by(DialogLog.created_at.desc(), DialogLog.id.desc())
        .limit(limit)
    )
    logs = list(result)
    logs.reverse()
    return logs


async def user_stats(session: AsyncSession, user_id: int) -> dict[str, int]:
    total_goals = await session.scalar(select(func.count(Goal.id)).where(Goal.user_id == user_id))
    completed_goals = await session.scalar(
        select(func.count(Goal.id)).where(Goal.user_id == user_id, Goal.status == GoalStatus.COMPLETED)
    )
    total_steps = await session.scalar(
        select(func.count(Step.id)).join(Goal, Goal.id == Step.goal_id).where(Goal.user_id == user_id)
    )
    done_steps = await session.scalar(
        select(func.count(Step.id))
        .join(Goal, Goal.id == Step.goal_id)
        .where(Goal.user_id == user_id, Step.status == StepStatus.DONE)
    )

    return {
        "total_goals": int(total_goals or 0),
        "completed_goals": int(completed_goals or 0),
        "total_steps": int(total_steps or 0),
        "done_steps": int(done_steps or 0),
    }
