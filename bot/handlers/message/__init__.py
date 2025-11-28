from aiogram import Router

from . import auth, export_users, info, menu, start, support


def get_message_handlers_router() -> Router:
    router = Router()
    router.include_router(start.router)
    router.include_router(info.router)
    router.include_router(support.router)
    router.include_router(menu.router)
    router.include_router(export_users.router)
    router.include_router(auth.router)

    return router
