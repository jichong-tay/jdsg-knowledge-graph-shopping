# Chat switching browser check

Run the isolated synthetic server and browser flow:

```bash
uv run python tests/browser/chat_server.py --port 8771
agent-browser --session chat-switch open http://127.0.0.1:8771/chat
agent-browser --session chat-switch eval --stdin < tests/browser/chat_switching.js
```

The server uses a temporary SQLite database and a deterministic fake runner. The
check covers selecting A, preserving its draft when stale B is removed, receiving
an A rename update without resubscribing, and sending from a new conversation.
