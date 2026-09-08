# Explore agent orchestration libraries

Parent: ../map.md
Type: research
Status: resolved
Resolution: out-of-scope

## Question

Compared with the chosen small Python agent loop, what concrete benefits, costs, and adoption triggers would LangGraph, PydanticAI, CrewAI, LangChain, Google ADK, and GitHub Copilot SDK offer this Shopping Assistant?

Compare current official documentation and, where necessary, source code for:

- Python 3.14 compatibility, dependency footprint, licensing, and local deployment requirements.
- Native Ollama and explicitly selected OpenAI-compatible model support, including streamed tool calls and provider portability.
- Pydantic tool validation, application-controlled read-tool allowlists, evidence handling, and prompt-injection boundaries.
- SQLite conversation ownership, checkpointing, interrupted turns, cancellation, reconnect, and retry semantics.
- Testing, evaluation, tracing, and whether telemetry or provider-managed state sends household data off-machine.
- Support for workflows and multiple agents, assessed against demonstrated shopping use cases rather than feature count alone.
- Migration effort from the small Python loop and the measurable complexity or reliability thresholds that would justify adoption.

Use the explicit Python loop as the baseline. Produce a primary-source comparison and a recommendation to retain it or revisit a specific alternative when an adoption trigger occurs. Findings do not authorize installation, a framework migration, or a change to the current no-framework decision.

## Comments

- Requested by the operator while choosing the initial Python loop. This is independent research and is not a dependency of the initial runtime or rollout plan. No library is installed by creating this ticket.

## Scope disposition

The operator subsequently narrowed the MVP to a working Ollama-backed chatbot on the existing homelab deployment and explicitly deferred orchestration-library research to a later phase. Closed as outside this destination; no comparison has been performed and no library has been selected or installed. Preserve this question as context for a future effort.
