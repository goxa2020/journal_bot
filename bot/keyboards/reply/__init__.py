from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для отмены."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=_("cancel_btn"))
    builder.adjust(1)
    return builder.as_markup()
