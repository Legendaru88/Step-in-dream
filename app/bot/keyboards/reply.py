from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_TEXTS = ["🎯 Мои цели", "➕ Новая цель", "📊 Статистика"]


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 Мои цели"), KeyboardButton(text="➕ Новая цель")],
            [KeyboardButton(text="📊 Статистика")],
        ],
        resize_keyboard=True,
    )
