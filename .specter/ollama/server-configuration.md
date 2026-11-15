# Ollama Server Configuration

**Tags:** ollama, configuration, environment-variables, systemd, kubernetes, spec-02

Source: ollama/ollama `docs/faq.mdx` (the old `docs/faq.md` URL now 404s).

## How configuration works

Ollama is configured entirely through environment variables on the server process. Under systemd, set them with `systemctl edit ollama.service` and add `Environment="KEY=value"` lines under `[Service]`, then `systemctl daemon-reload && systemctl restart ollama`. In Kubernetes, set them as `env:` on the Ollama container.

## Variables relevant to dsm-shai

| Variable | Default | Notes |
|----------|---------|-------|
| `OLLAMA_HOST` | `127.0.0.1:11434` | Bind address. In a pod it must be `0.0.0.0:11434` so the Service can reach it. Exposure is then controlled by the mesh (spec 08). |
| `OLLAMA_CONTEXT_LENGTH` | 4096 | Default context window. Agents need 32k+, so override it. Per request, `options.num_ctx` or `/set parameter num_ctx` overrides it. |
| `OLLAMA_KEEP_ALIVE` | 5m | Duration string (`10m`, `24h`), seconds, negative for forever, `0` to unload immediately. The per-request `keep_alive` overrides it. |
| `OLLAMA_MAX_LOADED_MODELS` | 3 x GPUs | Models resident at once, if they fit in VRAM. |
| `OLLAMA_NUM_PARALLEL` | 1 | Parallel requests per model. Memory scales with `NUM_PARALLEL x CONTEXT_LENGTH`. |
| `OLLAMA_MAX_QUEUE` | 512 | Queued requests before the server returns 503. |
| `OLLAMA_FLASH_ATTENTION` | auto | `1` forces on. Needed for a quantized KV cache. |
| `OLLAMA_KV_CACHE_TYPE` | `f16` | `q8_0` uses about 1/2 the memory with negligible quality loss. `q4_0` uses about 1/4 with more noticeable loss at long context. Global to all models. Models with a high GQA count (for example Qwen2) may be hit harder. |
| `OLLAMA_MODELS` | `/usr/share/ollama/.ollama/models` (Linux) | Model store. Put it on a PVC on the WSL ext4 volume. The process user needs read/write access. |
| `OLLAMA_NO_CLOUD=1` | off | Disables cloud features (cloud models and web search). Fits the "no cloud" constraint. It can also be set via `disable_ollama_cloud` in `~/.ollama/server.json`. |

## Checking and warming models

- `ollama ps` shows loaded models and the PROCESSOR column: `100% GPU` is fully on GPU, `100% CPU` is in system RAM, `48%/52% CPU/GPU` is a partial offload (slow, so avoid it).
- Preload with an empty request: `curl localhost:11434/api/generate -d '{"model":"qwen3:14b"}'` (same for `/api/chat`), or `ollama run <model> ""`.
- Unload with `ollama stop <model>` or `keep_alive: 0`. Pin with `keep_alive: -1`.

## Notes

- GPU access in containers needs the nvidia-container-toolkit. The FAQ does not cover Kubernetes, so the device plugin and `RuntimeClass` come from the k3s and NVIDIA docs.
- The OpenAI-compatible API is documented separately in `docs/api/openai-compatibility.mdx` and is not in the FAQ.
- Behind a proxy, set `HTTPS_PROXY` only. Setting `HTTP_PROXY` can break client connections, because model pulls use HTTPS only.
- Related upstream docs not ingested: `docs/gpu.mdx`, `docs/docker.mdx`, `docs/context-length.mdx`, `docs/troubleshooting.mdx`.
