# deploy/ollama

Ollama inference (spec 02). Single replica, `Recreate`, RTX 4080 via `RuntimeClass nvidia`, ClusterIP `ollama.ollama.svc:11434`.

## Models (pinned tags, never `latest`)

| Role | Tag | Notes |
|---|---|---|
| Chat | `qwen3:14b` (Q4_K_M) | tool calling verified |
| Embedding | `nomic-embed-text:v1.5` | 768-dim; pinned resident |
| VLM | `qwen2.5vl:3b` | image description verified |

Models live on the `ollama-models` PVC (50Gi, `local-path` on the WSL ext4 volume).

## Scheduling

- `OLLAMA_CONTEXT_LENGTH=32768`, flash attention on, KV cache `q8_0`, `NUM_PARALLEL=1`, `MAX_LOADED_MODELS=2`, `KEEP_ALIVE=10m`.
- `ollama-preload` Job pulls the three models and warms them. Idempotent: a re-run with models present completes in seconds with no re-download.
- `ollama-embed-pin` CronJob (every 5 min) re-pins the embedding model with `keep_alive: -1`. Needed because `/v1/embeddings` has no keep-alive parameter, so any embedding call resets the model to the default 10m.

## Measured (RTX 4080, 16376 MiB total)

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

- **Prompt limit = loaded context.** Ollama truncates any prompt longer than the loaded context, to about half of it, with a `truncating input prompt` warning. Callers (LiteLLM, Hermes, OpenViking) must keep prompts under 32k tokens.
- **64k context does not fit.** Tested `OLLAMA_CONTEXT_LENGTH=65536`: the scheduler shrank the loaded context to 40960 because only about 14.4 GiB is free. Staying at 32k.
- **Host memory pressure at load.** The pod's 12Gi cgroup limit triggers `disabling mmap ... due to host memory pressure` when a model loads. Performance only; no failures observed.
- **Cold chat load can evict the embed model.** If chat loads cold while embed is resident, the scheduler may unload embed. It reloads in under a second on the next call.
- The Service is ClusterIP only. The namespace-scoped denial (only `litellm` may call it) depends on spec 08 part B.
