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


def get_auth_error_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура после сбоя авторизации.

    «Ещё раз» повторяет запрос с теми же учётными данными (пароль лежит в
    состоянии только как Fernet-токен), «Сменить данные» — тот же вход, что и
    кнопка «Войти», «Отмена» возвращает в главное меню.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=_("auth.retry_btn"), callback_data="auth_retry")
    builder.button(text=_("auth.change_data_btn"), callback_data="auth_start")
    builder.button(text=_("cancel_btn"), callback_data="auth_cancel")
    builder.adjust(2, 1)
    return builder.as_markup()
