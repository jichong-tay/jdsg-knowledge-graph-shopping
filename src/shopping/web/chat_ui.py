"""The approved Conversation library layout, composed in the existing shell."""

from fasthtml.common import (
    H2,
    Aside,
    Button,
    Dialog,
    Div,
    Form,
    Header,
    Label,
    P,
    Section,
    Small,
    Textarea,
)
from stitchyard.ui import Icon, UiButton


def chat_page(model: str):
    return Section(
        Aside(
            UiButton("New conversation", id="chat-new", cls="new-chat"),
            P("Conversations", cls="rail-label"),
            Div(id="chat-library"),
            Button("Older conversations", id="chat-library-more", cls="chat-btn", hidden=True),
            P("Saved on this machine. Purchase records are read-only.", cls="rail-foot"),
            id="chat-rail",
            cls="conversation-rail",
            aria_label="Conversations",
        ),
        Div(
            Header(
                Div(
                    H2("New conversation", id="chat-title", cls="chat-title"),
                    Small(f"Ollama · {model}", id="chat-model", cls="chat-subtitle"),
                ),
                Div(
                    Button(
                        "Conversations", id="chat-history-toggle", cls="chat-btn mobile-history"
                    ),
                    Button("Rename", id="chat-rename", cls="chat-btn", disabled=True),
                    Button("Delete", id="chat-delete", cls="chat-btn danger", disabled=True),
                    cls="chat-actions",
                ),
                cls="chat-header",
            ),
            Div(
                P("Connecting…", id="chat-connection", role="status"),
                Button("Reconnect", id="chat-reconnect", cls="chat-btn", hidden=True),
                cls="chat-connection",
            ),
            Div(
                Button("Older messages", id="chat-older", cls="chat-btn", hidden=True),
                Div(
                    Div(
                        Icon("messages-square"),
                        H2("Ask about your purchases"),
                        P(
                            "Find recorded orders, items, dates and prices. "
                            "Answers link back to your evidence."
                        ),
                        cls="chat-empty",
                    ),
                    id="chat-transcript",
                ),
                id="chat-messages",
                cls="chat-messages",
                aria_label="Conversation messages",
            ),
            Form(
                Label("Message", fr="chat-message", cls="sr-only"),
                Textarea(
                    id="chat-message",
                    name="message",
                    maxlength=4000,
                    rows=2,
                    placeholder="Ask about your purchases…",
                    autocomplete="off",
                ),
                Div(
                    Small("Enter to send · Shift+Enter for a new line"),
                    Button("Retry", id="chat-retry", type="button", cls="chat-btn", hidden=True),
                    Button("Stop", id="chat-stop", type="button", cls="chat-btn", hidden=True),
                    UiButton("Send", id="chat-send", type="submit", disabled=True),
                    cls="composer-bottom",
                ),
                P(
                    "Check the linked evidence. Incomplete responses are marked.",
                    cls="composer-foot",
                ),
                id="chat-composer",
                cls="composer-zone",
            ),
            cls="chat-column",
        ),
        Dialog(id="chat-dialog", cls="chat-dialog"),
        id="shopping-chat",
        hx_history="false",
        cls="chat-surface layout-a",
    )
