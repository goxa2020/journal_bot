from aiogram import Router


def get_handlers_router() -> Router:
    from .message import get_message_handlers_router
    from .callback import get_callback_handlers_router


    router = Router()
    router.include_router(get_message_handlers_router())
    router.include_router(get_callback_handlers_router())


    return router
