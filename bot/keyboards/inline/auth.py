from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_cancel_inline_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопка отмены для шагов авторизации.

    Reply-клавиатуру нельзя прикрепить к редактируемому сообщению
    (`edit_message_text` принимает только inline), поэтому отмена — inline.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=_("cancel_btn"), callback_data="auth_cancel")
    return builder.as_markup()
