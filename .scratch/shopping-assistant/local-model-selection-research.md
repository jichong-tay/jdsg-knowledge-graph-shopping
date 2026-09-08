# Local model selection for the shopping assistant

Research date: 2026-09-08. Primary-source review only; no homelab model execution, downloads, upgrades, or configuration changes. This is a shortlist and a validation proposal, not a claim that any candidate has passed the application workload.

## Recommendation

**Subsequent operator decision:** use installed `qwen3.5:9b` with thinking disabled
for the MVP. The comparison and repetitions proposed below are research options,
not implementation prerequisites. Retain normal synthetic integration checks and
revisit model selection only if an actual problem appears. No model has been tested
on the host by this research.

**Test `qwen3.5:9b` first, directly against `gemma4:12b`. Start both in non-thinking mode.** Qwen is the strongest first candidate in this review for the combination of structured tools, instruction following, and memory headroom; Gemma remains a credible challenger. This is an engineering inference from the evidence below, not a measured winner. Being installed establishes availability, not correct tool use or acceptable performance.

Keep the comparison small: two models already available, the same four tool schemas, the same synthetic receipt cases, and the agreed runtime limits. If neither passes, try `ministral-3:8b` as a non-thinking alternative; if latency or memory is the problem, test `qwen3.5:4b`. Do not build routing, add an orchestration framework, or automatically switch models.

## What is actually known about the host

The operator supplied Ubuntu 24.04.4 LTS, i5-3570K, 15 GiB RAM with about 10 GiB available, RTX 3060 with 12 GiB VRAM and about 11.3 GiB free, and Ollama 0.30.10. Both services were running; `shopping-app` could list models through loopback; Ollama listened on `127.0.0.1:11434`. No model was loaded in the supplied `ollama ps` output. These are operator-provided observations, not independently reproduced measurements.

The target is one active response, four bounded read tools, 8,192 total context tokens, 768 generated tokens per model request, at most four model requests/eight tool calls/180 seconds. The application needs correct product matching, purchase dates, integer-cent facts, clarification when ambiguous, and evidence IDs—not image understanding or competition mathematics.

## Candidate comparison

Package sizes below are current Ollama download sizes, **not total GPU-memory requirements**. Each listed standard tag currently uses Q4_K_M quantization. The published numbers are publisher evaluations of named upstream models, not these quantized packages on this host.

| Candidate | Package | Relevant primary evidence | Proposed role |
|---|---|---|---|
| `qwen3.5:9b` | 6.6 GB | Its exact model card reports BFCL-V4 66.1 and IFEval 91.5; native tool-use examples and configurable thinking. | First candidate; test correctness and latency. |
| `gemma4:12b` | 7.6 GB | Google documents native function calling and configurable thinking; the 12B model scores 69.0 on its reported Tau2 average. | Direct challenger, not a guaranteed default. |
| `qwen3.5:4b` | 3.4 GB | Same Qwen evaluation table reports BFCL-V4 50.3 and IFEval 89.8. | Smaller candidate if the 9B is too slow/heavy; lower tool benchmark is a caution. |
| `ministral-3:8b` | 6.0 GB | Official Instruct card provides function-calling examples; Ollama exposes native tools. | Alternative if the first pair fails; not proven superior. |
| `qwen3:8b` | 5.2 GB | Official card supports tools in thinking and non-thinking modes. | Older baseline; no reason from this review to download it before testing the newer pair. |
| `qwen3:4b` | 2.5 GB | Ollama lists tools and thinking; already installed. | Cheap diagnostic baseline, not assumed accurate enough. |

Sources for exact package metadata: [Qwen3.5 9B](https://ollama.com/library/qwen3.5:9b), [Gemma4 12B](https://ollama.com/library/gemma4:12b), [Qwen3.5 4B](https://ollama.com/library/qwen3.5:4b), [Ministral3 8B](https://ollama.com/library/ministral-3:8b), [Qwen3 8B](https://ollama.com/library/qwen3:8b), [Qwen3 4B](https://ollama.com/library/qwen3:4b). Capability/evaluation sources: [exact Qwen3.5 9B card](https://huggingface.co/Qwen/Qwen3.5-9B), [Google Gemma4 card](https://ai.google.dev/gemma/docs/core/model_card_4), [Ministral3 8B Instruct card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512), [Qwen3 8B card](https://huggingface.co/Qwen/Qwen3-8B).

### What those benchmarks do not establish

Do not compare BFCL and Tau2 as though they were one score. Publisher configurations, evaluation harnesses, quantization, and generation budgets differ. In particular, the Qwen3.5 card recommends 32,768 output tokens for general queries and 81,920 for complex benchmark problems; it does not establish those results at 768 tokens or with thinking disabled. Its card also recommends much larger context for preserving complex thinking capability. Our deliberately short, tool-grounded workload must be validated separately. [Qwen3.5 model card](https://huggingface.co/Qwen/Qwen3.5-9B)

The Ollama Qwen3.5 tag page includes a family benchmark table for the **397B-A17B** model; those numbers are not the 9B's results. The Gemma4 tag page's table omits 12B, whereas Google's updated model card includes it. Use the exact-size evidence above. [Qwen tag page](https://ollama.com/library/qwen3.5:9b), [Gemma tag page](https://ollama.com/library/gemma4:12b), [Google card](https://ai.google.dev/gemma/docs/core/model_card_4)

Ministral's card separates Reasoning and Instruct benchmark sections. The Reasoning model's mathematics scores must not be attributed to the Instruct candidate. Its function-calling example establishes an intended interface, not success with our schemas. [Ministral3 card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512)

## Runtime implications

Ollama's native API accepts a top-level `think` setting for supported thinking models; its docs say thinking defaults on. Explicitly request `think: false` for the first comparison and inspect both the tool calls and final content. Do not rely on merely hiding the thinking text in the UI. [Ollama thinking](https://docs.ollama.com/capabilities/thinking)

Qwen3.5 supports a hard API/template non-thinking switch but does not officially support Qwen3's prompt-based soft switch. Qwen3 also provides a hard switch. Google documents removing its thinking control token to disable reasoning; in Ollama, let the provider's template/parser handle model syntax instead of hand-inserting control tokens. [Qwen3.5 card](https://huggingface.co/Qwen/Qwen3.5-9B), [Qwen3 card](https://huggingface.co/Qwen/Qwen3-8B), [Google card](https://ai.google.dev/gemma/docs/core/model_card_4)

**Inference:** The short output budget makes non-thinking the sensible starting profile: the model should select a tool and summarize returned facts, while Python handles exact money and validation. If failures require reasoning, compare a separate explicitly budgeted profile; do not silently enlarge the accepted limits or infer that the model itself is unusable from output truncation.

**Inference:** The available VRAM favors a single quantized small/mid-sized model with spare room. The installed 17 GB `qwen3.6:27b` package already exceeds free VRAM before context/runtime allocations; it is a poor first choice for an interactive MVP on this older CPU. The custom `gemma4:12b-hermes` tag has unknown provenance, template, and parameters, so do not rank it from its name. Inspect its definition only if stock candidates fail.

Set the proposed context explicitly rather than relying on an installation default. Ollama documents that larger context consumes more memory and recommends checking CPU/GPU placement with `ollama ps`. Aim for `100% GPU` at the intended context; package size alone cannot establish this. No trustworthy measured tokens-per-second result for this exact host, package, and workload was established by this review. [Ollama context guidance](https://docs.ollama.com/context-length)

Current library availability does not prove that the exact installed Ollama build, tag digest, parser, and GPU backend work together. Preserve the existing no-auto-update policy; a compatibility problem is a reason for a deliberate diagnosis and retest, not an automatic upgrade.

## Small proof that a model works here

This proposed check belongs in the existing MVP acceptance work, not a new evaluation platform. Use only synthetic fixtures and the actual four proposed tool schemas; do not send raw email or household data to public services.

1. Record server version, model digest/quantization, context/output limits, thinking mode, and sampling options for each run. Do not assume the same temperature is optimal for different families.
2. Run the same roughly ten cases against each candidate: latest purchase; bounded product history; recent receipts then one receipt's details; ambiguous products; absent product; empty dataset; follow-up reference; pagination; a tool error; and malicious instructions inside a product name.
3. Inspect the whole model → validated tool call → synthetic tool result → final answer cycle. A single successful tool-call JSON is not a passing assistant. Include more than one consecutive tool step and streamed tool-argument assembly.
4. Repeat cases three times. Require valid allowed tool names/arguments, correct supplied dates/cents/IDs, no fabricated evidence, clarification rather than guessing, and honest partial/error answers. Any fabricated receipt fact/evidence fails the candidate pending a fix and retest.
5. Measure cold start separately from warm requests. Record end-to-end latency, tool/model passes, time to first useful visible text, peak VRAM, and `ollama ps` GPU/CPU placement. Test a near-8K conversation, not only a tiny greeting. Require no OOM and completion within the agreed 180-second ceiling; choose between passing candidates using normal-case responsiveness, not the ceiling alone.

Passing this small check would support a practical MVP choice, not prove universal reliability. The research outcome is a **Qwen3.5 9B vs Gemma4 12B test order**; the homelab result must decide the deployed model.
