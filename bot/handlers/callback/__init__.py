from aiogram import Router

from . import auth, info


def get_callback_handlers_router() -> Router:
    router = Router()
    router.include_router(info.router)
    router.include_router(auth.router)

    return router
