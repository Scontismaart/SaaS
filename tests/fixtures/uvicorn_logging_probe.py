"""Minimal ASGI target for a real Uvicorn access/error logging probe."""

import logging
import os

if os.environ.get("MELPIS_PROBE_APP_GUARD") == "1":
    from src.core.logging_filter import configure_logging

    configure_logging()


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] == "http":
        if scope["path"] == "/api/auth/google/callback":
            logging.getLogger("uvicorn.error").warning("SYNTHETIC_ERROR_LOG_PROBE")
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})
