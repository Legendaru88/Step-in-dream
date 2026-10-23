import io
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.goal import Goal, GoalStatus
from app.models.step import Step, StepStatus
from app.services.evidence import assess_image, prepare_image
from app.services.llm import OpenRouterError
from app.utils.db import get_or_create_user, get_goal_for_user
from app.bot.handlers.evidence import accept_evidence, image_evidence

CONTEXT = {"goals": [{"id": 1, "title": "Read", "steps": [{"id": 7, "title": "Read book"}]}], "caption": "", "history": []}
DECISION = {"verdict": "sufficient", "step_id": 7, "observation": "Read", "reason": "Supports step"}


def picture(fmt="PNG"):
    out = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(out, format=fmt)
    return out.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_accepts_real_image(fmt):
    assert prepare_image(picture(fmt), 10000).startswith("data:image/jpeg;base64,")


@pytest.mark.parametrize("content,limit", [(b"%PDF-test", 100), (b"not a png", 100), (picture("GIF"), 10000), (picture(), 10)])
def test_rejects_unsupported_corrupt_oversized(content, limit):
    with pytest.raises(ValueError):
        prepare_image(content, limit)


@pytest.mark.asyncio
async def test_split_never_passes_goals_or_caption_to_vision():
    client = SimpleNamespace(_settings=SimpleNamespace(image_analysis_mode="split", vision_model="qwen"),
        _chat=AsyncMock(side_effect=["Observed book", json.dumps(DECISION)]))
    result = await assess_image(client, "data:image/jpeg;base64,test", CONTEXT)
    assert result.step_id == 7
    first, second = client._chat.call_args_list
    assert first.kwargs["model"] == "qwen"
    assert "Read book" not in str(first.args)
    assert "Observed book" in str(second.args)
    assert "base64" not in str(second.args)


@pytest.mark.asyncio
async def test_direct_is_single_multimodal_call():
    client = SimpleNamespace(_settings=SimpleNamespace(image_analysis_mode="direct"), _chat=AsyncMock(return_value=json.dumps(DECISION)))
    await assess_image(client, "data:image/jpeg;base64,test", CONTEXT)
    assert client._chat.await_count == 1
    assert "image_url" in str(client._chat.call_args)


@pytest.mark.parametrize("bad", ["not json", json.dumps({**DECISION, "step_id": 99}), json.dumps({**DECISION, "step_id": None}), json.dumps({**DECISION, "verdict": "done"})])
@pytest.mark.asyncio
async def test_invalid_decision_cannot_target_other_step(bad):
    client = SimpleNamespace(_settings=SimpleNamespace(image_analysis_mode="direct"), _chat=AsyncMock(return_value=bad))
    with pytest.raises(OpenRouterError):
        await assess_image(client, "image", CONTEXT)


@pytest.mark.asyncio
async def test_confirmation_ownership_idempotency_and_progress():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = await get_or_create_user(session, 111, "owner")
        goal = Goal(user_id=user.id, title="Goal", status=GoalStatus.ACTIVE)
        session.add(goal)
        await session.flush()
        step = Step(goal_id=goal.id, title="Step", order=1, status=StepStatus.PENDING)
        session.add(step)
        await session.commit()
        storage = MemoryStorage()
        state = FSMContext(storage, StorageKey(bot_id=1, chat_id=111, user_id=111))
        pending = {"token": "abc", "goal_id": goal.id, "step_id": step.id, "expires": time.time()+60}
        # Even forged pending data cannot authorize access to a different owner.
        await state.update_data(pending_evidence=pending)
        callback = SimpleNamespace(data="evidence_accept_abc", from_user=SimpleNamespace(id=222, username="other"), answer=AsyncMock(), message=None)
        await accept_evidence(callback, session, state)
        assert step.status == StepStatus.PENDING
        await state.update_data(pending_evidence=pending)
        callback.from_user = SimpleNamespace(id=111, username="owner")
        await accept_evidence(callback, session, state)
        assert step.status == StepStatus.DONE
        assert goal.progress == 100
        assert goal.status == GoalStatus.COMPLETED
        await accept_evidence(callback, session, state)
        assert step.status == StepStatus.DONE  # repeat does not toggle it back
        assert (await state.get_data())["pending_evidence"] is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_reject_pdf_before_network():
    message = SimpleNamespace(from_user=SimpleNamespace(id=1), photo=None,
        document=SimpleNamespace(mime_type="application/pdf"), answer=AsyncMock())
    state = SimpleNamespace(get_state=AsyncMock(return_value=None))
    await image_evidence(message, None, state)
    assert "PDF" in message.answer.call_args.args[0]


@pytest.mark.parametrize("provider_fails", [False, True])
@pytest.mark.asyncio
async def test_photo_flow_keeps_progress_until_confirmation(monkeypatch, provider_fails):
    import app.bot.handlers.evidence as handler
    from app.services.evidence import EvidenceDecision
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = await get_or_create_user(session, 333, "tester")
        goal = Goal(user_id=user.id, title="Course", status=GoalStatus.ACTIVE, progress=0)
        session.add(goal)
        await session.flush()
        step = Step(goal_id=goal.id, title="Finish course", order=1, status=StepStatus.PENDING)
        session.add(step)
        await session.commit()
        state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=333, user_id=333))
        image = picture()
        async def download(path, destination, timeout):
            destination.write(image)
        bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path="test.jpg", file_size=len(image))), download_file=download)
        message = SimpleNamespace(from_user=SimpleNamespace(id=333, username="tester"),
            photo=[SimpleNamespace(file_id="test", file_unique_id="unique", file_size=len(image))],
            document=None, caption="Course result", bot=bot, answer=AsyncMock())
        assessment = AsyncMock(side_effect=OpenRouterError("unavailable")) if provider_fails else AsyncMock(
            return_value=EvidenceDecision(**{**DECISION, "step_id": step.id}))
        monkeypatch.setattr(handler, "assess_image", assessment)
        await image_evidence(message, session, state)
        assert step.status == StepStatus.PENDING
        assert goal.progress == 0
        pending = (await state.get_data()).get("pending_evidence")
        if provider_fails:
            assert pending is None
            assert "Прогресс не изменён" in message.answer.call_args.args[0]
        else:
            assert pending["step_id"] == step.id
            assert "reply_markup" in message.answer.call_args.kwargs
            from sqlalchemy import select
            from app.models.dialog import DialogLog
            logs = list(await session.scalars(select(DialogLog)))
            assert len(logs) == 2
            record = json.loads(logs[1].content)
            assert record["file_unique_id"] == "unique"
            assert record["step_id"] == step.id
    await engine.dispose()
