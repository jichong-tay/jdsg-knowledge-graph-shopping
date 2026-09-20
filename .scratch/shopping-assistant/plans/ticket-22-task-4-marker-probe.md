# Ticket 22 Task 4 marker probe

Date: 2026-09-20. Target: Ollama 0.30.10, `qwen3.5:9b`, `think: false`,
native `/api/chat`, non-streaming synthetic probe. No household data was used.

## Probe contract

The system prompt extended the existing evidence contract with this exact
instruction:

> Respond in exactly one typed mode. Start conversation/help/acknowledgement
> with `[[conversation]]`. Start clarification with `[[clarification]]`. Start
> unsupported with `[[unsupported]]`. For factual shopping answers use evidence
> markers from tool results. Never invent evidence.

Cases were greeting, help, thanks, a mixed greeting plus “what did I buy most
recently?”, and an unsupported weather request. Tools were supplied but no tool
results were fabricated or injected.

## Observations

- Greeting: `[[conversation]]` and no tool call.
- Help: `[[conversation]]` and no tool call.
- Thanks: `[[conversation]]` and no tool call.
- Mixed greeting/purchase question: `[[conversation]]` plus a
  `list_recent_orders` tool call. This preserves the required read for the
  factual part, but the provisional prose should be discarded by the runtime.
- Unsupported weather question: incorrectly emitted `[[conversation]]` and
  uncited prose explaining the limitation; it omitted `[[unsupported]]`.

## Decision and limits

Keep the existing plain-text marker protocol as the wire encoding. It works for
conversation modes and mixed factual requests, while native JSON was not tested
because this probe did not establish that structured output is compatible with
the installed model plus tools. The parser must treat markers as a validated
mode hint, never as proof: application-owned wording should render
conversation/help/acknowledgement and unsupported responses, and arbitrary model
text in those modes must not become a factual answer. Mixed requests still
require a tool call and evidence validation. The unsupported failure means the
model cannot be trusted to classify every mode; add parser tests and use a
deterministic application fallback when the requested mode is unsupported or
missing.

## Typed-marker follow-up

A second probe required distinct markers `[[conversation:greeting]]`,
`[[conversation:thanks]]`, `[[conversation:help]]`, `[[clarification]]`, and
`[[unsupported]]`, with explicit examples. Greeting, thanks, and unsupported
followed the requested marker; help omitted its marker; ambiguous shopping text
put `[[clarification]]` at the end; mixed purchase text called
`list_recent_orders` but returned no text; and a future-need forecast called
`search_products` instead of selecting unsupported. This rejects trusting typed
markers as a reliable model classifier. Keep markers as hints only, with strict
start-of-response parsing and application-owned deterministic handling for help,
unsupported, and clarification when the marker is missing or misplaced.

## Native JSON-schema probe

The installed Ollama/model was also tested with native `format` set to this
schema, alongside the full tool schemas:

```json
{"type":"object","properties":{"mode":{"type":"string","enum":["greeting","thanks","help","clarification","unsupported","grounded"]},"text":{"type":"string"}},"required":["mode","text"],"additionalProperties":false}
```

The purpose was to classify help, a future-need forecast, an ambiguous request,
and a mixed greeting plus recent-order question while preserving tool calls.
The result was not usable: help returned ordinary prose that was not JSON;
forecast, ambiguous, and mixed requests returned empty content while emitting
tool calls (`list_purchase_items` or `list_recent_orders`). Thus the native
schema did not produce a valid mode object and cannot be used as the wire
contract with this model/tool configuration. Retain the plain marker protocol,
with application validation and deterministic fallbacks.

## Reproduction details

The typed follow-up system prompt was:

> Classify the user's request and begin your response with exactly one marker
> from this list: `[[conversation:greeting]]` for greetings only;
> `[[conversation:thanks]]` for thanks/acknowledgement only;
> `[[conversation:help]]` for asking what you can do; `[[clarification]]` only
> when a shopping product/request is ambiguous; `[[unsupported]]` for
> non-shopping requests or unsupported capabilities. A request containing a
> personal shopping fact question always requires a fresh read tool call and
> must not be classified as conversation. Examples: “hello” =>
> `[[conversation:greeting]]`; “thanks” => `[[conversation:thanks]]`; “what can
> you do?” => `[[conversation:help]]`; “weather tomorrow?” =>
> `[[unsupported]]`; “which milk did I buy?” => call a read tool. Never invent
> evidence.

Both probes POSTed `model: qwen3.5:9b`, `think: false`, `stream: false`,
`keep_alive: 5m` was omitted in the direct probe, `options: {num_ctx: 8192,
num_predict: 180}` for typed markers and `{num_ctx: 8192, num_predict: 768}`
for JSON, and the complete `tool_schemas()` array. The JSON probe additionally
sent the schema as the top-level `format` field. Questions were exactly:
`What can you help me with?`, `Will I need more milk next week?`, `What did I
buy?`, and `Hello! What did I buy most recently?`.
