import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.goal import Goal, GoalStatus
from app.models.step import Step, StepStatus
from app.utils.db import get_or_create_user, user_stats


@pytest.mark.asyncio
async def test_get_or_create_user_returns_existing() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user1 = await get_or_create_user(session, telegram_id=777, username="first")
        await session.commit()

    async with Session() as session:
        user2 = await get_or_create_user(session, telegram_id=777, username="updated")
        await session.commit()

    assert user1.id == user2.id
    assert user2.username == "updated"

    await engine.dispose()


@pytest.mark.asyncio
async def test_user_stats_counts_data() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = await get_or_create_user(session, telegram_id=12, username="u")
        goal = Goal(user_id=user.id, title="Goal", status=GoalStatus.ACTIVE, progress=0)
        session.add(goal)
        await session.flush()

        session.add_all(
            [
                Step(goal_id=goal.id, title="one", order=1, status=StepStatus.DONE),
                Step(goal_id=goal.id, title="two", order=2, status=StepStatus.PENDING),
            ]
        )
        await session.commit()

    async with Session() as session:
        stats = await user_stats(session, user_id=1)

    assert stats["total_goals"] == 1
    assert stats["completed_goals"] == 0
    assert stats["total_steps"] == 2
    assert stats["done_steps"] == 1

    await engine.dispose()
