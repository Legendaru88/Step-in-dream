from aiogram import Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from app.bot.handlers.evidence import router as evidence_router

from app.bot.handlers.dialog import router as dialog_router
from app.bot.handlers.goals import router as goals_router
from app.bot.handlers.navigation import router as navigation_router
from app.bot.handlers.smart_dialog import router as smart_dialog_router
from app.bot.handlers.start import router as start_router
from app.bot.middlewares.db import DbSessionMiddleware


def setup_dispatcher() -> Dispatcher:
    dp = Dispatcher(events_isolation=SimpleEventIsolation())

    db_middleware = DbSessionMiddleware()
    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    # Priority: explicit commands/dialog state first.
    dp.include_router(start_router)
    dp.include_router(evidence_router)
    dp.include_router(dialog_router)
    dp.include_router(goals_router)
    dp.include_router(navigation_router)
    dp.include_router(smart_dialog_router)

    return dp
