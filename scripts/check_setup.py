"""Check private Compose configuration without polling or printing credentials."""
import argparse
import asyncio

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from app.config import get_settings
from app.services.llm import OpenRouterClient


async def main(network):
    settings = get_settings()
    missing = [name for name, value in [
        ("BOT_TOKEN", settings.bot_token),
        ("OPENROUTER_API_KEY", settings.openrouter_api_key),
        ("OPENROUTER_PROXY_URL", settings.openrouter_proxy_url),
        ("TELEGRAM_PROXY_URL", settings.telegram_proxy_url),
    ] if not value or value.startswith("YOUR_")]
    if missing:
        print("Missing configuration: " + ", ".join(missing))
        return 1
    print("Settings OK. Model: " + settings.openrouter_model)
    print("Both proxies configured (Telegram API and files share one session).")
    if not network:
        return 0

    success = True
    bot = Bot(token=settings.bot_token, session=AiohttpSession(
        proxy=settings.telegram_proxy_url, timeout=15))
    try:
        await bot.get_me()
        print("Telegram getMe OK")
    except Exception as exc:
        print("Telegram check failed: " + type(exc).__name__)
        success = False
    finally:
        await bot.session.close()

    try:
        reply = await OpenRouterClient()._chat(
            [{"role": "user", "content": "Reply only OK"}], max_tokens=30)
        if not reply:
            raise ValueError("Empty response")
        print("Model request OK")
    except Exception as exc:
        print("Model check failed: " + type(exc).__name__)
        success = False
    print("No polling, updates, messages or webhook changes. See docs/OPERATIONS.md.")
    return 0 if success else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args().network)))
