from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fasthtml.common import (
    A,
    Aside,
    Body,
    Button,
    Dd,
    Div,
    Dl,
    Dt,
    Head,
    Header,
    Html,
    Link,
    Main,
    Meta,
    Nav,
    P,
    Script,
    Span,
    Title,
)
from starlette.requests import Request
from stitchyard.assets import StitchyardAssets
from stitchyard.ui import (
    Icon,
    IconButton,
    StatusBadge,
)

from shopping.config import Settings

_ASSETS = StitchyardAssets()

_NAV_ITEMS = (
    ("/", "Overview", "layout-dashboard"),
    ("/orders", "Orders", "shopping-basket"),
    ("/chat", "Chat", "messages-square"),
    ("/graph", "Graph", "network"),
    ("/system", "System", "activity"),
)

_THEME_BOOTSTRAP = """
(function(){
  try {
    var saved = localStorage.getItem('shopping-theme');
    var theme = saved || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.dataset.theme = theme;
  } catch (_) {}
})();
"""

_DISPLAY_TIMEZONE = ZoneInfo("Asia/Singapore")


def register_assets(app: Any) -> None:
    _ASSETS.register(app)


def _nav_link(path: str, label: str, icon: str, *, current_path: str) -> Any:
    active = current_path == path or (path != "/" and current_path.startswith(f"{path}/"))
    return A(
        Icon(icon, "nav-icon"),
        Span(label),
        href=path,
        cls=f"nav-link{' is-active' if active else ''}",
        aria_current="page" if active else None,
        hx_get=None if path == "/chat" or current_path == "/chat" else path,
        hx_target="#main-view",
        hx_swap="outerHTML",
        hx_push_url="true",
        data_nav_path=path,
    )


def _sidebar(current_path: str) -> Any:
    return Aside(
        Div(
            Div(
                Span("S", cls="brand-mark"),
                Div(
                    Span("Shopping", cls="brand-name"), P("Local intelligence", cls="brand-kicker")
                ),
                cls="brand",
            ),
            IconButton("Close navigation", "x", cls="sidebar-close", data_sidebar_close="true"),
            cls="sidebar-brand-row",
        ),
        Nav(
            P("Workspace", cls="nav-section-label"),
            *(
                _nav_link(path, label, icon, current_path=current_path)
                for path, label, icon in _NAV_ITEMS
            ),
            aria_label="Primary",
            cls="primary-nav",
        ),
        Div(
            StatusBadge("Healthy", "Local only"),
            P("Private data stays on this machine.", cls="sidebar-note"),
            cls="sidebar-footer",
        ),
        id="app-sidebar",
        cls="app-sidebar",
        aria_label="Application navigation",
    )


def main_view(title: str, eyebrow: str, content: Any, *, environment: str) -> Any:
    return Div(
        Header(
            Div(
                IconButton("Open navigation", "menu", cls="menu-toggle", data_sidebar_open="true"),
                Div(P(eyebrow, cls="topbar-eyebrow"), Span(title, cls="topbar-title")),
                cls="topbar-leading",
            ),
            Div(
                Span(environment, cls="environment-chip"),
                IconButton("Change color theme", "sun-moon", data_theme_toggle="true"),
                cls="topbar-actions",
            ),
            cls="app-topbar",
        ),
        Main(content, id="page-content", tabindex="-1"),
        id="main-view",
        cls="main-view",
        data_page_title=title,
    )


def document(
    title: str,
    eyebrow: str,
    content: Any,
    *,
    current_path: str,
    environment: str,
) -> Any:
    return Html(
        Head(
            Title(f"{title} · Shopping"),
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Meta(name="color-scheme", content="light dark"),
            Link(rel="icon", href="data:,"),
            Script(_THEME_BOOTSTRAP),
            *_ASSETS.headers(include_meta=False),
            Link(rel="stylesheet", href="/static/shopping.css?v=20260922"),
        ),
        Body(
            A("Skip to content", href="#page-content", cls="skip-link"),
            Div(
                _sidebar(current_path),
                main_view(title, eyebrow, content, environment=environment),
                cls="app-shell",
            ),
            Button(
                "",
                type="button",
                cls="sidebar-scrim",
                aria_label="Close navigation",
                data_sidebar_close="true",
            ),
            Div(id="drawer-root", aria_live="polite"),
            Div(id="app-live-region", cls="sr-only", aria_live="polite", aria_atomic="true"),
            *_ASSETS.footers(),
            Script(src="/static/shopping.js"),
            Script(src="/static/vendor/cytoscape-3.34.3.min.js?v=20260920", defer=True),
            Script(src="/static/graph.js?v=20260922", defer=True),
            Script(src="/static/chat.js", defer=True) if current_path == "/chat" else None,
        ),
        lang="en",
    )


def status_badge(status: str) -> Any:
    mapping = {
        "placed": ("Healthy", "Placed"),
        "completed": ("Healthy", "Completed"),
        "cancelled": ("Stale", "Cancelled"),
        "refunded": ("Warning", "Refunded"),
        "unknown": ("Warning", "Unknown"),
        "parsed": ("Healthy", "Parsed"),
        "failed": ("Critical", "Failed"),
        "needs_review": ("Warning", "Needs review"),
    }
    tone, label = mapping.get(status, ("Unavailable", status.replace("_", " ").title()))
    return StatusBadge(tone, label, cls=f"status-{status.replace('_', '-')}")


def money(cents: int | None, currency: str) -> str:
    if cents is None:
        return "—"
    return f"{currency} {cents / 100:,.2f}"


def compact_list(items: Iterable[str]) -> str:
    return " · ".join(item for item in items if item)


def _page_response(
    request: Request,
    settings: Settings,
    *,
    title: str,
    eyebrow: str,
    current_path: str,
    content,
):
    if request.headers.get("HX-Request") == "true":
        return main_view(title, eyebrow, content, environment=settings.environment)
    return document(
        title,
        eyebrow,
        content,
        current_path=current_path,
        environment=settings.environment,
    )


def _display_datetime(value: str | None) -> str:
    if value is None:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.utcoffset() is None:
        return value
    return parsed.astimezone(_DISPLAY_TIMEZONE).strftime("%d %b %Y, %H:%M SGT")


def _definition_rows(items: list[tuple[str, str]]):
    return Dl(
        *(Div(Dt(label), Dd(value, cls="mono"), cls="definition-row") for label, value in items),
        cls="definition-list",
    )
