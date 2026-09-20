from __future__ import annotations

from typing import Any

from fasthtml.common import (
    H1,
    H2,
    Button,
    Details,
    Div,
    Form,
    Input,
    Label,
    Option,
    P,
    Section,
    Select,
    Span,
    Summary,
    Textarea,
)
from stitchyard.ui import PageFrame, Panel

from shopping.knowledge.models import NODE_TYPES


def graph_page(*, analysis_date: str) -> Any:
    return PageFrame(
        Div(
            H1("Knowledge graph"),
            P(
                "Larger products appear in more orders. Select a product to see "
                "past delivery dates.",
                cls="graph-header-hint",
            ),
            cls="graph-header",
        ),
        Panel(
            Form(
                Div(
                    Label(
                        Span("Search products or families", cls="sr-only"),
                        Input(
                            name="query",
                            maxlength="200",
                            placeholder="Search products or families",
                        ),
                        cls="graph-search-label",
                    ),
                    Button("Search", type="submit"),
                    Details(
                        Summary("Filters"),
                        Div(
                            Label(
                                "Record versions",
                                Select(
                                    Option("Latest version per order", value="current"),
                                    Option("Include earlier versions", value="history"),
                                    name="mode",
                                ),
                            ),
                            Label("Start date", Input(type="date", name="start_date")),
                            Label("End date", Input(type="date", name="end_date")),
                            Div(
                                *(
                                    Label(
                                        node_type.title(),
                                        Input(
                                            type="checkbox",
                                            name="node_types",
                                            value=node_type,
                                            checked=True,
                                        ),
                                    )
                                    for node_type in NODE_TYPES
                                ),
                                id="graph-node-types",
                            ),
                            Button("Apply filters", type="submit"),
                            cls="graph-filter-grid",
                        ),
                    ),
                    cls="graph-search-row",
                ),
                id="graph-filters",
            ),
            Div(
                *(
                    Button(label, type="button", data_graph_action=action)
                    for action, label in (
                        ("zoom-in", "Zoom in"),
                        ("zoom-out", "Zoom out"),
                        ("fit", "Fit"),
                        ("reset", "Reset"),
                        ("focus", "Focus selected"),
                        ("clear-product-focus", "All products"),
                        ("refresh", "Refresh"),
                        ("overview-next", "Next"),
                    )
                ),
                id="graph-actions",
            ),
            Div(
                P("Loading graph…", id="graph-status", role="status", aria_live="polite"),
                P("", id="graph-error", role="alert"),
                Div("Graph results will appear here.", id="graph-counts"),
                cls="graph-status-row",
            ),
            Div(
                Div(
                    Div(
                        Div(
                            id="graph-canvas",
                            role="img",
                            aria_label="Shopping knowledge graph",
                        ),
                        P("Drag to pan. Use Fit to show the whole graph.", cls="graph-canvas-hint"),
                        Details(
                            Summary("Browse relationships"),
                            Div("No graph loaded yet.", id="graph-relationships", role="list"),
                            cls="graph-browse-panel",
                        ),
                        cls="graph-stage",
                    ),
                    Div(
                        Div(
                            H2("Explore your purchases"),
                            P("Select a product or family to inspect its evidence and timeline."),
                            id="graph-inspector",
                        ),
                        Div(
                            *(
                                Span(
                                    node_type.title(),
                                    cls=f"graph-type-pill graph-type-{node_type}",
                                    data_node_type=node_type,
                                )
                                for node_type in NODE_TYPES
                            ),
                            id="graph-legend",
                        ),
                        P(
                            "Product circle size = qualifying orders in the selected period.",
                            cls="graph-frequency-note",
                        ),
                        cls="graph-side-panel",
                    ),
                    cls="graph-workspace",
                ),
                Div(id="graph-timeline"),
                Details(
                    Summary("Coverage and scope"),
                    P(
                        "Counts cover successfully parsed purchase records only. Unparsed messages "
                        "and purchases outside this archive are absent. Purchase Date is the "
                        "scheduled delivery date in Singapore, not confirmed fulfilment. "
                        "Quantities remain per exact Product and recorded unit; package sizes are "
                        "not converted.",
                        id="graph-coverage-note",
                    ),
                ),
            ),
            id="graph-content",
        ),
        Details(
            Summary("Family management"),
            Section(
                H2("Review memberships"),
                Label(
                    "Review mode",
                    Select(
                        Option("Pending", value="pending"),
                        Option("Current", value="current"),
                        Option("History", value="history"),
                        id="graph-review-mode",
                    ),
                ),
                Button("Load reviews", type="button", data_graph_action="reviews"),
                Button("Next reviews", type="button", data_graph_action="reviews-next"),
                P("", id="graph-review-status", role="status"),
                Div(id="graph-review-list"),
                id="graph-review",
                cls="graph-section",
            ),
            Section(
                H2("Create family"),
                P(
                    "Choices come from viewed graph records; use Graph search to locate more.",
                    id="graph-choice-guidance",
                ),
                Form(
                    Label("Family name", Input(name="name", maxlength="120", required=True)),
                    Label(
                        "Definition", Textarea(name="definition", maxlength="2000", required=True)
                    ),
                    Button("Create family", type="submit"),
                    id="graph-family-form",
                    cls="graph-form",
                ),
                P("", id="graph-mutation-status", role="status"),
                H2("Propose membership"),
                Form(
                    Label(
                        "Product",
                        Select(name="product_id", id="graph-product-select", required=True),
                    ),
                    Label(
                        "Family", Select(name="family_id", id="graph-family-select", required=True)
                    ),
                    Label(
                        "Origin",
                        Select(
                            Option("Manual", value="manual"),
                            Option("Inferred", value="inferred"),
                            name="origin",
                        ),
                    ),
                    Label(
                        "Method",
                        Input(name="method", value="manual-ui", maxlength="120", required=True),
                    ),
                    Label("Rationale", Textarea(name="rationale", maxlength="2000", required=True)),
                    Button("Propose membership", type="submit"),
                    id="graph-proposal-form",
                    cls="graph-form",
                ),
                cls="graph-section",
            ),
        ),
        id="shopping-graph",
        data_analysis_date=analysis_date,
        hx_history="false",
    )
