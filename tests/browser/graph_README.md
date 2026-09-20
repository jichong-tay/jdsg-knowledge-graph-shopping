# Graph browser review

These checks use only synthetic fixtures and a disposable temporary SQLite
database. They do not access the operator database or call a model.

Start the server in one terminal:

```bash
uv run python tests/browser/graph_server.py
```

Useful variants are `--unassigned` for products without an accepted family and
`--empty` for an empty graph. Use `--port 8766` (the default) or pass the same
port to the scripts.

Run the browser checks from another terminal:

```bash
agent-browser --session ticket21 open http://127.0.0.1:8766/graph
agent-browser --session ticket21 eval --stdin < tests/browser/graph_explorer.js
agent-browser --session ticket21 open http://127.0.0.1:8766/graph
agent-browser --session ticket21 eval --stdin < tests/browser/graph_reviews.js
agent-browser --session ticket21 open http://127.0.0.1:8766/graph
agent-browser --session ticket21 eval --stdin < tests/browser/graph_navigation.js
agent-browser --session ticket21 open http://127.0.0.1:8766/graph
agent-browser --session ticket21 eval --stdin < tests/browser/graph_readability.js
```

`graph_explorer.js` expects the default accepted Family/Product seed. Run it after
opening a fresh Graph URL. `graph_reviews.js` writes only to the disposable
synthetic database and can be used with `--unassigned`; it exercises review
controls. `graph_navigation.js` covers navigation/history restore behavior. If a
different port is used, open that matching URL before each fresh read; the scripts
do not change the server origin.

Purchase-focused checks use six or twelve synthetic dated orders:

```bash
uv run python tests/browser/graph_server.py --port 8780 --purchase-focused --purchase-orders 6
agent-browser --session purchase-focus open http://127.0.0.1:8780/graph
agent-browser --session purchase-focus eval --stdin < tests/browser/graph_purchase_focus.js

uv run python tests/browser/graph_server.py --port 8782 --purchase-focused --purchase-orders 12
agent-browser --session purchase-focus-12 open http://127.0.0.1:8782/graph
agent-browser --session purchase-focus-12 eval --stdin < tests/browser/graph_purchase_focus.js
```
