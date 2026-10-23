"""Real dispatcher + isolated SQLite + fake Telegram; opt-in real Luna calls."""
import io
import os
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, EditMessageText, GetFile
from aiogram.types import Update, Message, File, InlineKeyboardMarkup
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot import setup_dispatcher
from app.bot.states import GoalDialog
from app.database import Base
from app.models.goal import Goal
from app.models.step import StepStatus
from app.services.llm import OpenRouterClient
from app.utils.db import get_goal_for_user, get_or_create_user

LIVE = os.getenv("TGGOALS_LIVE") == "1"
PLAN = "ЦЕЛЬ: Нарисовать кота\nЭТАПЫ:\n1. Нарисовать контур кота\n2. Раскрасить кота\n3. Нарисовать фон"


class FakeTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        out = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(out, format="PNG")
        self.image = out.getvalue()

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=len(self.calls), date=datetime.now(timezone.utc),
                chat={"id": int(method.chat_id), "type": "private"}, text=method.text,
                reply_markup=method.reply_markup if isinstance(method.reply_markup, InlineKeyboardMarkup) else None)
        if isinstance(method, GetFile):
            return File(file_id="image", file_unique_id="unique", file_path="test.png", file_size=len(self.image))
        return True

    async def stream_content(self, url, **kwargs):
        yield self.image

    @property
    def texts(self):
        return [m.text for m in self.calls if isinstance(m, (SendMessage, EditMessageText))]

    @property
    def hints(self):
        return [t for t in self.texts if t.startswith("Необязательный фотоотчёт:")]


@pytest.fixture(scope="module")
def dispatcher():
    # Production routers are singletons and may only be attached once.
    return setup_dispatcher()


@pytest_asyncio.fixture
async def journey(dispatcher, tmp_path, monkeypatch):
    import app.bot.middlewares.db as middleware
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "journey.db"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(middleware, "SessionLocal", factory)
    await dispatcher.storage.close()
    dispatcher.storage.storage.clear()
    transport = FakeTelegram()
    bot = Bot("123456:TEST_TOKEN_FOR_FAKE_TRANSPORT", session=transport)

    class Journey:
        db = factory
        telegram = transport
        dp = dispatcher
        user_id = 9001
        sequence = 0

        async def send(self, text=None, callback=None, user_id=None, **media):
            self.sequence += 1
            uid = user_id or self.user_id
            user = {"id": uid, "is_bot": False, "first_name": "Synthetic"}
            msg = {"message_id": self.sequence, "date": datetime.now(timezone.utc),
                "chat": {"id": uid, "type": "private"}, "from": user}
            if callback:
                msg["text"] = "Synthetic bot response"
                msg["from"] = {"id": bot.id, "is_bot": True, "first_name": "Test bot"}
                update = Update.model_validate({"update_id": self.sequence, "callback_query": {
                    "id": str(self.sequence), "from": user, "chat_instance": "test",
                    "data": callback, "message": msg}})
            else:
                update = Update.model_validate({"update_id": self.sequence,
                    "message": {**msg, **media, **({"text": text} if text else {})}})
            return await dispatcher.feed_update(bot, update)

        async def state(self, user_id=None):
            return dispatcher.fsm.get_context(bot=bot, chat_id=user_id or self.user_id, user_id=user_id or self.user_id)

        async def goals(self):
            async with factory() as session:
                user = await get_or_create_user(session, self.user_id, None)
                ids = list(await session.scalars(select(Goal.id).where(Goal.user_id == user.id)))
                return [await get_goal_for_user(session, user.id, i) for i in ids]

        async def create(self, text="Хочу нарисовать кота", revision=None):
            await self.send("/new")
            await self.send(text)
            assert await (await self.state()).get_state() == GoalDialog.waiting_goal_confirmation.state
            if revision:
                await self.send(callback="draft_edit")
                await self.send(revision)
            await self.send(callback="draft_save")
            assert await (await self.state()).get_state() is None
            return (await self.goals())[-1]

    yield Journey()
    await bot.session.close()
    await engine.dispose()


@pytest.fixture
def models(monkeypatch):
    plan = AsyncMock(return_value=PLAN)
    hint = AsyncMock(return_value="Когда закончишь контур, можешь прислать фото рисунка. Это необязательно; зачёт — отдельной кнопкой.")
    monkeypatch.setattr(OpenRouterClient, "propose_goal_plan", plan)
    monkeypatch.setattr(OpenRouterClient, "suggest_photo_report", hint)
    monkeypatch.setattr(OpenRouterClient, "classify_intent", AsyncMock(return_value="UPDATE_PROGRESS"))
    monkeypatch.setattr(OpenRouterClient, "congratulate", AsyncMock(return_value="Поздравляю!"))
    return plan, hint


@pytest.mark.asyncio
async def test_creation_revision_save_buttons_text_and_durable_repeat_guard(journey, models):
    _, hint = models
    goal = await journey.create(revision="Добавь фон")
    assert any("после сохранения цели" in t for t in journey.telegram.texts)
    assert len(journey.telegram.hints) == 1
    assert len(goal.steps) == 3
    assert all("фото" not in s.title.lower() for s in goal.steps)
    # Push offer out of recent history; permanent marker must still suppress repeats.
    from app.models.dialog import DialogRole
    from app.utils.db import add_dialog_log
    async with journey.db() as session:
        for _ in range(12):
            await add_dialog_log(session, goal.user_id, DialogRole.USER, "Synthetic later message")
        await session.commit()
    before = hint.await_count
    await journey.send(callback=f"goal_view_{goal.id}")
    await journey.send(callback=f"step_done_{goal.steps[0].id}")
    await journey.send("Я сделал контур")
    assert hint.await_count == before
    assert len(journey.telegram.hints) == 1


@pytest.mark.asyncio
async def test_legacy_goal_view_and_toggle_can_introduce_hint(journey, models):
    _, hint = models
    # A provider failure at save should not permanently mark an undelivered hint.
    hint.return_value = ""
    goal = await journey.create()
    hint.return_value = "Можно прислать фото контура, если хочешь."
    await journey.send(callback=f"goal_view_{goal.id}")
    assert len(journey.telegram.hints) == 1
    hint.return_value = ""
    goal2 = await journey.create()
    hint.return_value = "Когда нарисуешь фон, можешь прислать фото."
    await journey.send(callback=f"step_done_{goal2.steps[0].id}")
    assert len(journey.telegram.hints) == 2
    # A different owner cannot cause a suggestion or a progress change.
    before = hint.await_count
    await journey.send(callback=f"step_done_{goal2.steps[1].id}", user_id=9002)
    assert hint.await_count == before
    assert (await journey.goals())[-1].steps[1].status == StepStatus.PENDING


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["draft", "revision", "saved"])
async def test_refusal_survives_history_and_new_goal(journey, models, stage):
    _, hint = models
    await journey.send("/new")
    await journey.send("Нарисовать кота")
    if stage == "revision":
        await journey.send(callback="draft_edit")
    if stage == "saved":
        await journey.send(callback="draft_save")
    await journey.send("Не хочу присылать фотографии, больше не предлагай фото")
    count = hint.await_count
    if stage != "saved":
        await journey.send(callback="draft_save")
    await journey.create("Хочу нарисовать дом")
    await journey.send("Сделал рисунок")
    assert hint.await_count == count
    assert any("больше не буду" in t for t in journey.telegram.texts) or stage == "revision"


@pytest.mark.asyncio
async def test_completed_goal_and_callback_during_draft_do_not_offer(journey, models):
    _, hint = models
    hint.return_value = ""
    goal = await journey.create()
    before = hint.await_count
    await journey.send("/new")
    await journey.send(callback=f"goal_view_{goal.id}")
    assert hint.await_count == before
    await journey.send("/start")
    for step in goal.steps:
        await journey.send(callback=f"step_done_{step.id}")
    count = hint.await_count
    await journey.send(callback=f"goal_view_{goal.id}")
    assert hint.await_count == count
    assert (await journey.goals())[0].progress == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["photo", "png", "jpeg"])
async def test_image_dispatcher_manual_accept_repeat_ttl_and_ownership(journey, models, monkeypatch, kind):
    from app.bot.handlers import evidence
    from app.services.evidence import EvidenceDecision
    goal = await journey.create()
    monkeypatch.setattr(evidence, "assess_image", AsyncMock(return_value=EvidenceDecision(
        verdict="sufficient", step_id=goal.steps[0].id, observation="Виден контур кота", reason="Соответствует шагу")))
    if kind == "photo":
        media = {"photo": [{"file_id": "photo", "file_unique_id": "image", "width": 64, "height": 64}]}
    else:
        media = {"document": {"file_id": "doc", "file_unique_id": "image", "mime_type": "image/" + kind}}
        if kind == "jpeg":
            out = io.BytesIO()
            Image.new("RGB", (64, 64), "white").save(out, format="JPEG")
            journey.telegram.image = out.getvalue()
    await journey.send(**media)
    assert (await journey.goals())[0].progress == 0
    state = await journey.state()
    pending = (await state.get_data())["pending_evidence"]
    assert any(getattr(m, "reply_markup", None) for m in journey.telegram.calls[-1:])
    # Even forged state for another actor cannot bypass DB ownership.
    other = await journey.state(9002)
    await other.update_data(pending_evidence=pending)
    await journey.send(callback="evidence_accept_" + pending["token"], user_id=9002)
    assert (await journey.goals())[0].progress == 0
    await state.update_data(pending_evidence={**pending, "expires": time.time() - 1})
    await journey.send(callback="evidence_accept_" + pending["token"])
    assert (await journey.goals())[0].progress == 0
    await state.update_data(pending_evidence=pending)
    await journey.send(callback="evidence_accept_" + pending["token"])
    assert (await journey.goals())[0].steps[0].status == StepStatus.DONE
    await journey.send(callback="evidence_accept_" + pending["token"])
    assert (await journey.goals())[0].steps[0].status == StepStatus.DONE


@pytest.mark.asyncio
async def test_image_in_draft_and_pdf_rejected_before_download(journey, models):
    await journey.send("/new")
    await journey.send(photo=[{"file_id": "photo", "file_unique_id": "i", "width": 64, "height": 64}])
    assert "Сначала закончи" in journey.telegram.texts[-1]
    await journey.send("/start")
    await journey.send(document={"file_id": "pdf", "file_unique_id": "p", "mime_type": "application/pdf"})
    assert "PDF" in journey.telegram.texts[-1]
    assert not any(isinstance(m, GetFile) for m in journey.telegram.calls)


@pytest.mark.skipif(not LIVE, reason="Set TGGOALS_LIVE=1 for real Luna; Telegram remains fake")
@pytest.mark.asyncio
@pytest.mark.parametrize("goal_text,visual", [
    ("Хочу нарисовать кота гуашью на бумаге", True),
    ("Хочу сделать кормушку для птиц из дерева", True),
    ("Хочу убрать рабочий стол", True),
    ("Хочу прочитать роман Война и мир", False),
    ("Хочу научиться спокойнее относиться к критике и понимать свои эмоции", False),
    ("Хочу понять теорему Пифагора", False),
])
async def test_live_luna_full_draft_revision_save_and_buttons(journey, goal_text, visual):
    goal = await journey.create(goal_text, revision="Сделай этапы проще и короче")
    draft_notes = [t for t in journey.telegram.texts if "Необязательный фотоотчёт (после сохранения" in t]
    assert bool(draft_notes) == visual, journey.telegram.texts
    assert bool(journey.telegram.hints) == visual, journey.telegram.texts
    assert all("фото" not in s.title.lower() for s in goal.steps)
    before = len(journey.telegram.hints)
    await journey.send(callback=f"goal_view_{goal.id}")
    await journey.send(callback=f"step_done_{goal.steps[0].id}")
    await journey.send("Я выполнил первый этап")
    assert len(journey.telegram.hints) == before

@pytest.mark.skipif(not LIVE, reason="Set TGGOALS_LIVE=1 for real Luna")
@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['view', 'toggle', 'text', 'chat'])
async def test_live_legacy_goal_first_offer_from_each_entry(journey, action, monkeypatch):
    from app.models.step import Step
    from app.models.goal import GoalStatus
    async with journey.db() as session:
        user = await get_or_create_user(session, journey.user_id, None)
        goal = Goal(user_id=user.id, title='Нарисовать кота на бумаге', status=GoalStatus.ACTIVE, progress=0)
        session.add(goal)
        await session.flush()
        for order,title in enumerate(['Нарисовать контур кота', 'Раскрасить кота', 'Нарисовать фон'], 1):
            session.add(Step(goal_id=goal.id, title=title, order=order, status=StepStatus.PENDING))
        await session.commit()
    goal = (await journey.goals())[0]
    if action == 'view':
        await journey.send(callback=f'goal_view_{goal.id}')
    elif action == 'toggle':
        await journey.send(callback=f'step_done_{goal.steps[0].id}')
    elif action == 'text':
        await journey.send('Я нарисовал контур кота, хочу отметить первый этап выполненным')
    else:
        # Force CHAT routing only: both the contextual reply and photo decision
        # still use the real model. The classifier is covered by the text case.
        monkeypatch.setattr(OpenRouterClient, 'classify_intent', AsyncMock(return_value='CHAT'))
        await journey.send('Рисунок кота уже закончен, я рад результату!')
    assert len(journey.telegram.hints) == 1, journey.telegram.texts

@pytest.mark.skipif(not LIVE, reason="Set TGGOALS_LIVE=1 for real Luna multimodal")
@pytest.mark.asyncio
async def test_live_luna_png_assessment_then_manual_confirmation(journey):
    from PIL import ImageDraw
    from app.models.step import Step
    from app.models.goal import GoalStatus
    async with journey.db() as session:
        user = await get_or_create_user(session, journey.user_id, None)
        goal = Goal(user_id=user.id, title='Нарисовать цветные фигуры', status=GoalStatus.ACTIVE, progress=0)
        session.add(goal)
        await session.flush()
        session.add(Step(goal_id=goal.id, title='Нарисовать красный круг на белом фоне', order=1, status=StepStatus.PENDING))
        await session.commit()
    image = Image.new('RGB', (512,512), 'white')
    ImageDraw.Draw(image).ellipse((100,100,412,412), fill='red')
    out = io.BytesIO(); image.save(out, format='PNG')
    journey.telegram.image = out.getvalue()
    await journey.send(document={'file_id':'synthetic', 'file_unique_id':'circle', 'mime_type':'image/png'})
    assert (await journey.goals())[0].progress == 0
    pending = (await (await journey.state()).get_data()).get('pending_evidence')
    assert pending, journey.telegram.texts
    await journey.send(callback='evidence_accept_' + pending['token'])
    assert (await journey.goals())[0].progress == 100
