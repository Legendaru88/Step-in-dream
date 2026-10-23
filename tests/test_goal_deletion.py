from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.handlers.goals import ask_delete_goal, cancel_delete, delete_goal, router
from app.bot.keyboards.inline import goal_details_keyboard
from app.database import Base
from app.models.dialog import DialogLog, DialogRole
from app.models.goal import Goal
from app.models.step import Step
from app.utils.db import get_or_create_user, get_goal_for_user


def callback(data, user_id=111):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, username="tester"),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,expected",
    [
        ("goal_delete_1", ask_delete_goal),
        ("goal_delete_123", ask_delete_goal),
        ("goal_delete_confirm_123", delete_goal),
        ("goal_delete_cancel_123", cancel_delete),
        ("goal_delete_bad", None),
    ],
)
async def test_delete_callback_routes_to_expected_handler(data, expected):
    # Check registered filters: direct handler calls alone miss the original bug.
    matches = []
    for handler in router.callback_query.handlers:
        accepted, _ = await handler.check(callback(data))
        if accepted:
            matches.append(handler.callback)
    assert matches == ([] if expected is None else [expected])


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["confirm", "cancel", "other_user"])
async def test_goal_deletion_flow(action):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            user = await get_or_create_user(session, 111, "tester")
            goal = Goal(user_id=user.id, title="Test goal")
            session.add(goal)
            await session.flush()
            step = Step(goal_id=goal.id, title="Test step", order=1)
            log = DialogLog(user_id=user.id, goal_id=goal.id,
                            role=DialogRole.USER, content="Goal history")
            session.add_all([step, log])
            await session.commit()
            goal_id, step_id, log_id = goal.id, step.id, log.id
            goal = await get_goal_for_user(session, user.id, goal_id)
            button = goal_details_keyboard(goal).inline_keyboard[-1][0]
            request = callback(button.callback_data)
            await ask_delete_goal(request)
            keyboard = request.message.edit_text.call_args.kwargs["reply_markup"]
            assert [b.callback_data for b in keyboard.inline_keyboard[0]] == [
                f"goal_delete_confirm_{goal_id}", f"goal_delete_cancel_{goal_id}"
            ]
            assert await session.get(Goal, goal_id) is not None

            if action == "cancel":
                request.data = keyboard.inline_keyboard[0][1].callback_data
                await cancel_delete(request, session)
                request.answer.assert_awaited_with("Отменено")
            else:
                request.data = keyboard.inline_keyboard[0][0].callback_data
                if action == "other_user":
                    request.from_user.id = 222
                await delete_goal(request, session)
                request.answer.assert_awaited_with(
                    "Цель не найдена" if action == "other_user" else "Цель удалена"
                )
            await session.commit()

        # Read back in a fresh session to verify the persisted result and cascade.
        async with factory() as session:
            assert (await session.get(Goal, goal_id) is None) == (action == "confirm")
            assert (await session.get(Step, step_id) is None) == (action == "confirm")
            log = await session.get(DialogLog, log_id)
            assert log is not None
            assert log.goal_id == (None if action == "confirm" else goal_id)
            if action == "confirm":
                repeat = callback(f"goal_delete_confirm_{goal_id}")
                await delete_goal(repeat, session)
                repeat.answer.assert_awaited_with("Цель не найдена")
    finally:
        await engine.dispose()
