from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import main_menu_keyboard
from app.utils.db import get_or_create_user

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return

    await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )
    await session.commit()

    await message.answer(
        "Привет! Я «Шаг к мечте». Помогу разбить цель на этапы и отслеживать прогресс. Начни с кнопки «➕ Новая цель».",
        reply_markup=main_menu_keyboard(),
    )
