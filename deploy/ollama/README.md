# deploy/ollama

Ollama inference (spec 02). Single replica, `Recreate`, RTX 4080 via `RuntimeClass nvidia`, ClusterIP `ollama.ollama.svc:11434`.

## Models (pinned tags, never `latest`)

| Role | Tag | Notes |
|---|---|---|
| Chat | `llama3.1:8b` (Q4_K_M, 128K native) | 64K served; tool calls verified; replaces `qwen3:14b` (see decision below) |
| Embedding | `nomic-embed-text:v1.5` | 768-dim; pinned resident |
| VLM | `qwen2.5vl:3b` | image description verified |

Models live on the `ollama-models` PVC (50Gi, `local-path` on the WSL ext4 volume).

## Scheduling

- `OLLAMA_CONTEXT_LENGTH=65536`, flash attention on, KV cache `q8_0`, `NUM_PARALLEL=1`, `MAX_LOADED_MODELS=2`, `KEEP_ALIVE=10m`.
- `ollama-preload` Job pulls the three models and warms them. Idempotent: a re-run with models present completes in seconds with no re-download.
- `ollama-embed-pin` CronJob (every 5 min) re-pins the embedding model with `keep_alive: -1`. Needed because `/v1/embeddings` has no keep-alive parameter, so any embedding call resets the model to the default 10m.

## Decision: chat model and 64K context (2026-11-16)

Hermes Agent refuses any model below 64K context. `qwen3:14b` cannot serve 64K, but not because of VRAM: its trained context length is 40960 (`ollama show qwen3:14b`), and Ollama clamps any larger `num_ctx` to it. Measured 2026-11-16: asking for 64000 loads at 40960 and uses 11.79 GiB of the 16 GiB. (An earlier version of this note blamed the card.) The same cap applies to every `qwen3` 8b/14b tag, so only models with a native context of at least 64K qualify. The chat model is now `llama3.1:8b`, which runs at 64K with `q8_0` KV and fits beside the embedding model. `qwen3:14b` stays on the PVC for rollback but is no longer preloaded.

## Measured (RTX 4080, 16376 MiB total)

Chat at 64K (`llama3.1:8b`, the current configuration):

| State | Measured | Source |
|---|---|---|
| Chat loaded at 65536 context | 8.9 GiB model VRAM, 100% GPU | `ollama ps` |
| VLM after swap (65536 context) | 4.11 GiB | `ollama ps` |
| Long prompt | 46,841 tokens accepted, no truncation; early marker recalled correctly at 5k, 21k and 47k tokens | API |
| Tool call | well-formed `tool_calls` | API |
| Swap | VLM evicts chat; chat reloads in about 4 s after eviction | API |

Earlier baseline with `qwen3:14b` at 32k (kept for reference):

| State | Measured | Source |

| State | Measured | Source |
|---|---|---|
| Chat (`qwen3:14b`) + embed, steady state | 11.09 + 0.31 GiB model VRAM; 12.9 GiB device used | `ollama ps`, `nvidia-smi` |
| VLM (`qwen2.5vl:3b`) + embed after swap | 3.17 GiB model VRAM | `ollama ps` |
| Chat context | 32768 tokens, 100% GPU (`size_vram == size`) | `ollama ps` |

Spec estimate for steady state was 14.0 GiB, which included a 1.0 GiB display reserve; the measured device figure of 12.9 GiB includes the display and CUDA context, so the 15.0 GiB ceiling holds with about 2 GiB to spare.

## Verified behaviour

- Long prompt: 28,843 tokens accepted at 32k context, completes with `finish_reason: stop`, both markers recalled.
- Tool call: `tool_calls` response with well-formed arguments.
- Swap: VLM request evicts chat and leaves embed resident; chat request evicts VLM and leaves embed resident. No OOM in the server log.

## Limits and deviations (read before wiring callers)

- **Prompt limit = loaded context.** Ollama truncates any prompt longer than the loaded context, to about half of it, with a `truncating input prompt` warning. Callers must keep prompts under 65536 tokens. (An earlier 30k test was itself truncated: it was above the 32k context, and the "16k" result was the truncation.)
- **qwen3:14b cannot reach 64K** because its native context is 40960, not because of VRAM (see the decision above). Ollama clamps `num_ctx` to the model's trained length, whatever the KV type.
- **The `llama3.1` template forces a tool call.** When tools are supplied, its Go template rewrites the last user message to "respond with a JSON for a function call", so a request that needs no tool still gets a call (15 of 15 plain questions in the 2026-11-16 benchmark). See `deploy/hermes/README.md`, "Why Hermes failed".
- **Embed model eviction.** With `MAX_LOADED_MODELS=2`, a swap can evict the embedding model (LRU). The `ollama-embed-pin` job re-pins it every 5 minutes, and a reload takes under a second. Embed is also evicted after a VLM swap when chat was used more recently.
- **Host memory pressure at load.** The pod's 12Gi cgroup limit triggers `disabling mmap ... due to host memory pressure` when a model loads. Performance only; no failures observed.
- **Cold chat load can evict the embed model.** If chat loads cold while embed is resident, the scheduler may unload embed. It reloads in under a second on the next call.
- The Service is ClusterIP only. The namespace-scoped denial (only `litellm` may call it) depends on spec 08 part B.
