from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _

router = Router(name="stubs")

# Кнопки главного меню, обработчики которых появятся в следующих фазах.
# Пока они отвечают «в разработке», а не молчат: иначе пользователь видит
# вечный спиннер на кнопке и решает, что бот сломан.
STUB_CALLBACKS = ("stats", "watch", "settings", "export", "help")


@router.callback_query(F.data.in_(STUB_CALLBACKS))
async def stub_handler(callback: CallbackQuery) -> None:
    await callback.answer(_("stub.in_development"))
