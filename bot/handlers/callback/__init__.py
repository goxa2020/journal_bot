from aiogram import Router
from . import info


def get_callback_handlers_router() -> Router:
    router = Router()
    router.include_router(info.router)


    return router
