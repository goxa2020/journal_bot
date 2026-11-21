from aiogram import Router

from . import auth, grades, info, stubs, sync


def get_callback_handlers_router() -> Router:
    router = Router()
    router.include_router(info.router)
    router.include_router(sync.router)
    router.include_router(grades.router)
    router.include_router(auth.router)
    router.include_router(stubs.router)

    return router
