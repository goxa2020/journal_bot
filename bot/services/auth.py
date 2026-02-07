from aiohttp.client_exceptions import ClientResponseError

from bot.services.api_client import InvalidCredsError, auth_post, get_fingerprint


async def authenticate_user(username: str, password: str) -> str:
    """Авторизация пользователя с его edu credentials.
    Возвращает access token пользователя
    """
    try:
        fingerprint = await get_fingerprint()

        auth_data = await auth_post(username, password, fingerprint)
        return str(auth_data.get("accessToken"))
    except (InvalidCredsError, ClientResponseError):
        return ""
