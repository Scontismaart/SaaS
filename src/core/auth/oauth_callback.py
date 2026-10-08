"""Safe failure boundary for third-party credential callbacks."""
import functools
import logging

from fastapi.responses import RedirectResponse


def safe_oauth_callback(channel: str):
    """Never return provider exception text, secrets or a user-controlled redirect."""
    def decorate(handler):
        @functools.wraps(handler)
        async def wrapped(*args, **kwargs):
            try:
                return await handler(*args, **kwargs)
            except Exception as error:
                logging.getLogger(__name__).warning(
                    "oauth_callback_failed channel=%s error_type=%s", channel, type(error).__name__,
                )
                return RedirectResponse(
                    url=f"/app/?{channel}=error&reason=server_error",
                    status_code=302,
                )
        return wrapped
    return decorate
