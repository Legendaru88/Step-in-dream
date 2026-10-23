import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from app.bot import setup_dispatcher
from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not configured")

    bot = Bot(token=settings.bot_token, session=AiohttpSession(proxy=settings.telegram_proxy_url or None))
    dp = setup_dispatcher()

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
