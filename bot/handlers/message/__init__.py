from aiogram import Router

from . import auth, export_users, grades, info, start, support, sync


def get_message_handlers_router() -> Router:
    router = Router()
    router.include_router(start.router)
    router.include_router(info.router)
    router.include_router(support.router)
    router.include_router(export_users.router)
    router.include_router(auth.router)
    router.include_router(grades.router)
    router.include_router(sync.router)

    return router
