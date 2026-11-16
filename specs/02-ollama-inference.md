# Spec 02 — Ollama Inference

**Status:** DONE (spec 08 part B NetworkPolicy check and the `litellm` caller check still pending; see deploy/ollama/README.md)

> **Amendment (2026-11-16):** the chat model is `llama3.1:8b` (Q4_K_M, 128K native), not `qwen3:14b`, and `OLLAMA_CONTEXT_LENGTH` is 65536. Reason: Hermes Agent refuses any model below 64K context, and `qwen3:14b` cannot serve 64K on this card (the scheduler shrinks it to 40960 with q8 and q4_0 KV). The VRAM measurements are in deploy/ollama/README.md. The VLM and embedding models are unchanged.

## Purpose
Run a single Ollama instance on the k3s cluster as the only local inference endpoint. It serves a tool-calling chat model, an embedding model and a small vision-language model inside the 16GB RTX 4080 VRAM budget. Depends on Spec 01 (platform-foundation) for the cluster, NVIDIA device plugin and namespaces.

## Behavior
- Deploy Ollama as a single-replica Deployment (strategy `Recreate`) in namespace `ollama` with `runtimeClassName: nvidia` and `nvidia.com/gpu: 1`. Expose it through a ClusterIP Service on port 11434.
- Back `/root/.ollama` with a PVC (at least 50Gi) on the WSL ext4 volume, not a `/mnt/c` path. Models must survive pod restarts.
- Serve the OpenAI-compatible API at `/v1` (chat completions with tool calls, embeddings) to LiteLLM (spec 09), its only caller. No other inference backend exists in the cluster; Hermes, OpenViking and Open WebUI reach models only through LiteLLM.
- Set the server env explicitly:
  - `OLLAMA_CONTEXT_LENGTH=32768`, raised to 65536 only if the budget below still holds.
  - `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0`, to roughly halve the KV cache.
  - `OLLAMA_NUM_PARALLEL=1`.
  - `OLLAMA_MAX_LOADED_MODELS=2`.
  - `OLLAMA_KEEP_ALIVE=10m`.
- Models (all pulled by tag, never `latest`):
  - Chat: `qwen3:14b` (Q4_K_M, about 9.3GB, tool-calling capable).
  - Embedding: `nomic-embed-text`.
  - VLM: `qwen2.5vl:3b`.
  - Models of 30B or larger are out of scope because they do not fit.
- Scheduling: the embedding model is pinned resident (`keep_alive: -1`) and shares the GPU with whichever of chat or VLM was used last. Chat and VLM are never loaded together; Ollama evicts the least recently used one on swap. Callers must tolerate a cold-load delay on swap.
- Model pull/preload: a post-deploy Job (or `postStart` hook) waits for `/api/tags`, runs `ollama pull` for all three models, then warms the embedding model with `keep_alive: -1` and the chat model with one trivial request. It must be idempotent, so a re-run with models already on the PVC does not re-download them.
- Add a readiness probe on `/api/tags` and a liveness probe on `/`. Set a generous startup probe for first boot.
- The Service is reachable only inside the cluster. There is no Ingress or NodePort.

### VRAM budget (16GB card, estimates in GiB, to be verified with `ollama ps` and `nvidia-smi`)
| Component | Chat + embed (steady state) | VLM + embed (after swap) |
|---|---|---|
| Windows/WDDM display + CUDA context reserve | 1.0 | 1.0 |
| `qwen3:14b` Q4_K_M weights | 9.3 | n/a (evicted) |
| KV cache at 32k, q8_0 (about 160KB/token fp16) | 2.7 | n/a |
| `qwen2.5vl:3b` weights + vision encoder | n/a | 3.2 |
| VLM KV cache (32k, q8_0, worst case) | n/a | 0.6 |
| Compute graph / scratch | 0.7 | 0.5 |
| `nomic-embed-text` | 0.3 | 0.3 |
| **Total** | **14.0** | **5.6** |

Chat and VLM together would need about 18.3GiB, which exceeds the card. This is why they swap and are not co-resident. Running the chat model at 64k would add about 2.7GiB of KV cache (q8_0), leaving less than 0.5GiB of headroom in steady state. It is permitted only if measured headroom is at least 0.5GiB.

## Acceptance Criteria
- [x] Namespace `ollama` has one Running pod using `RuntimeClass nvidia`, and `nvidia-smi` inside the pod shows the RTX 4080.
- [x] The models PVC is bound on the WSL ext4 volume, and the models are still present after `kubectl delete pod`.
- [ ] (waits for spec 09 `litellm` namespace) `curl http://ollama.ollama.svc:11434/v1/models` from a pod in the `litellm` namespace lists `qwen3:14b`, `nomic-embed-text` and `qwen2.5vl:3b`.
- [x] A `/v1/chat/completions` request with a tool definition to `qwen3:14b` returns a well-formed `tool_calls` response.
- [x] A `/v1/embeddings` request to `nomic-embed-text` returns a vector.
- [x] A `/v1/chat/completions` request with an image to `qwen2.5vl:3b` returns a description.
- [x] A chat request with a prompt of about 30k tokens completes, and `ollama ps` shows the model fully on GPU (100% GPU, no CPU offload) at the configured context.
- [x] Peak VRAM during steady state (chat + embed) is at most 15.0GiB. Measured values are recorded in the budget table.
- [x] Requesting the VLM while chat is loaded evicts chat and keeps the embedding model resident. The reverse swap also works, and no request fails with an out-of-memory error.
- [x] Re-running the preload Job with all models present completes without re-downloading and without errors.
- [ ] (ClusterIP verified; deny check waits for spec 08 part B) The Service is not reachable from outside the cluster. Once spec 08 is applied, requests from namespaces other than `litellm` are denied.
