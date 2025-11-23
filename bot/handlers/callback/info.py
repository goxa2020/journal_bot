from aiogram import F, Router, types
from aiogram.utils.i18n import gettext as _

router = Router(name="info")


@router.callback_query(F.data == "info")
async def info_handler(callback: types.CallbackQuery) -> None:
    """Information about bot."""
    await callback.answer(_("info button"))
