"""ASGI entry point for local development and systemd."""

from __future__ import annotations

import uvicorn

from app.config import load_settings
from app.web import create_app

settings = load_settings()
app = create_app(settings)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.validate_bind_host(), port=settings.port, workers=1)
