from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.db import get_or_create_user, user_stats
from app.utils.formatters import format_stats

router = Router()


@router.message(F.text == "📊 Статистика")
async def show_stats(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return

    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    stats = await user_stats(session, user.id)
    await session.commit()

    await message.answer(format_stats(stats))
