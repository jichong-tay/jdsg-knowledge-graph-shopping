from __future__ import annotations

import os
from pathlib import Path

from fasthtml.common import (
    fast_app,
)
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from shopping.assistant.runtime import run_attempt
from shopping.config import Settings
from shopping.storage.runtime import assert_supported_runtime
from shopping.storage.schema import assert_schema_current
from shopping.web.chat import register_chat
from shopping.web.health import register_health
from shopping.web.layout import register_assets
from shopping.web.orders import register_orders
from shopping.web.overview import register_overview
from shopping.web.products import register_products
from shopping.web.system import register_system

_STATIC_DIR = Path(__file__).with_name("static")


def create_app(settings: Settings, *, chat_runner=run_attempt):
    runtime = assert_supported_runtime(enforce_safe_sqlite=settings.enforce_safe_sqlite)
    assert_schema_current(settings.database_path, settings.migrations_dir)
    session_key_path = settings.data_dir / ".sesskey"
    app, _ = fast_app(
        key_fname=str(session_key_path),
        default_hdrs=False,
        pico=False,
        surreal=False,
        htmx=False,
        same_site="strict",
        sess_https_only=settings.environment == "production",
    )
    os.chmod(session_key_path, 0o600)
    app.state.settings = settings
    app.router.routes.insert(
        0,
        Mount(
            "/static",
            app=StaticFiles(directory=str(_STATIC_DIR)),
            name="shopping-static",
        ),
    )
    register_assets(app)
    register_chat(app, settings, runner=chat_runner)

    register_overview(app, settings, runtime)
    register_orders(app, settings)
    register_products(app, settings)
    register_system(app, settings)
    register_health(app, settings)
    return app
