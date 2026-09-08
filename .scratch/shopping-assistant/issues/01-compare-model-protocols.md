# Compare Ollama and OpenAI-compatible model protocols

Parent: ../map.md
Type: research
Status: resolved
Assignee: model-protocol-research

## Question

What verified capabilities and incompatibilities in the current Ollama and OpenAI-compatible APIs constrain a smallest safe provider interface for streamed text, tool calls, cancellation, usage metadata, and error handling?

## Comments

## Answer

Research completed and the committed report was inspected. Native Ollama and Chat Completions use different streaming formats and tool-call argument representations. The report recommends separate adapters behind a small shared interface for text deltas, assembled tool calls, terminal outcomes, optional usage, and typed errors.

- Assemble and correlate complete tool calls before application validation or execution.
- Cancellation closes the HTTP stream on a best-effort basis; terminal frames and usage are not guaranteed.
- Malformed streams, in-stream errors, and premature EOF must remain incomplete failures.
- A Chat Completions-compatible endpoint does not imply Responses API compatibility.

Report: [Ollama and OpenAI-compatible model protocols](/tmp/jdsg-research-model-protocols/docs/research/shopping-assistant-model-protocols.md).

Durable context pointer: branch `research/shopping-assistant-model-protocols`, commit `326023be9d6494ce62271974299e3014055bf65d`, repository path `docs/research/shopping-assistant-model-protocols.md`. Retrieve with `git show 326023be9d6494ce62271974299e3014055bf65d:docs/research/shopping-assistant-model-protocols.md` if the temporary worktree is removed.

These are research findings and recommendations. The runtime and streaming tickets still decide application lifecycle, retry, persistence, and disconnect behavior; this resolution does not settle those policies.
