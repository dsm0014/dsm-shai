# Ollama Concurrency, Model Swapping and VRAM

**Tags:** ollama, vram, concurrency, kv-cache, flash-attention, spec-02, spec-09

Source: ollama/ollama `docs/faq.mdx`.

## Two levels of concurrency

1. **Multiple models loaded at once.** This is only possible if there is enough memory. On GPU, a new model must fit *entirely* in VRAM to load alongside others.
2. **Parallel requests per model.** The model is configured for parallelism at load time if memory allows. Parallelism multiplies the context allocation, so a 2K context with 4 parallel requests becomes an 8K allocation.

## What happens when memory is short

- If a new model cannot fit while others are loaded, new requests are **queued** until idle models are unloaded to make room. Queued requests run in order.
- If the queue exceeds `OLLAMA_MAX_QUEUE` (default 512), Ollama returns `503`.
- Alternating requests between two large models therefore causes unload/reload swaps. This matters for the 16GB budget, where the chat and vision models do not fit together.

## Implications for dsm-shai (16GB RTX 4080)

- Keep `OLLAMA_NUM_PARALLEL=1`. Extra parallelism multiplies KV cache memory at 32k context.
- Set `OLLAMA_MAX_LOADED_MODELS=2` so the chat model and the small embedding model stay co-resident, while the VLM swaps in on demand.
- Use `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` to roughly halve KV cache memory versus `f16`, which makes 32k context affordable.
- Put a concurrency limit in the LiteLLM gateway (spec 09) so parallel agent requests do not force constant swaps. Ollama's own queue is the backstop.
- Request timeouts at the gateway and mesh must be long enough to cover a cold load (see spec 08 Ollama route settings).
- Verify placement with `ollama ps`. Any `CPU/GPU` split means the context or model is too large for VRAM.

## Multi-GPU behaviour (for reference)

If a model fits on a single GPU, Ollama loads it there to avoid PCIe traffic. Otherwise it spreads the model across GPUs. The target host has one GPU, so this does not apply.
