# Hermes Agent: Custom Endpoints, Ollama and Context Length

**Tags:** hermes, providers, ollama, litellm, context-length, tool-calling, spec-04

Source: hermes-agent.nousresearch.com/docs/integrations/providers (fetched through a summarizing tool, so verify critical details against the live page).

## Principle

Hermes works with any OpenAI-compatible endpoint: if a server implements `/v1/chat/completions`, Hermes can use it. Config lives in `~/.hermes/config.yaml`, and secrets live in `~/.hermes/.env`. For dsm-shai the endpoint is the LiteLLM gateway (spec 09), not Ollama directly.

## Three ways to configure a custom endpoint

1. `hermes model`, then "Custom endpoint" (interactive wizard, run outside a session).
2. Manual `config.yaml`:
   ```yaml
   model:
     default: qwen3:14b
     provider: custom
     base_url: http://litellm.litellm.svc:4000/v1
     context_length: 32768
   ```
   Add `api_key` here (or use `key_env`) when the endpoint needs a key.
3. Named providers in a `providers:` dict, for several endpoints:
   ```yaml
   providers:
     local:
       api: http://litellm.litellm.svc:4000/v1
       key_env: HERMES_LITELLM_KEY
       transport: chat_completions
   ```
   Switch in-session with `/model custom:local:chat`. Key names are inconsistent across the docs' examples (`api` vs `base_url`, `transport` vs `api_mode`, `key_env` vs `key_cmd`), so check the installed version's schema. `key_cmd` runs a command that prints a short-lived token.

`/model` inside a session only switches between already configured providers. Adding providers needs `hermes model` outside a session.

## Context length (the main gotcha)

- Hermes wants at least **64,000** tokens per the upstream docs. dsm-shai budgets 32k because of the 16GB VRAM limit. Treat this as a known deviation and verify behaviour at 32k (spec 04).
- The Ollama server default context is very low, so set `OLLAMA_CONTEXT_LENGTH` on the server (or bake `num_ctx` into a Modelfile) and verify with `ollama ps`.
- Hermes resolves the context window in this order: explicit `model.context_length` ("pinned"), per-model provider setting, persistent cache, endpoint `/v1/models`, upstream registries, then fallback defaults. When using Ollama or LiteLLM, auto-detection often fails (a symptom is "Context limit: 2048 tokens" at startup), so always pin `model.context_length` and keep it equal to the server value.
- `context_length` is the total window (input plus output). Output limits are server-side. Hermes no longer reads `max_tokens`.
- Symptoms of a too-small window: forgetting context, incoherent output, responses cut off mid-sentence. The remedy is a larger window or enabling context compression.

## Tool calling

Tool calls arriving as raw JSON text in replies means the server lacks tool-calling support.

| Server | Requirement |
|---|---|
| Ollama | Enabled by default, but the model must support tools (qwen3 does) |
| llama.cpp | `--jinja` |
| vLLM | `--enable-auto-tool-choice --tool-call-parser <parser>` |
| SGLang | `--tool-call-parser <parser>` |

Through LiteLLM, tool-call fields pass through to Ollama unchanged, so the model choice matters most.

## Vision and metadata

- `model.supports_vision: true` marks a custom model as natively multimodal.
- `catalog_provider: <name>` inherits context, reasoning and vision metadata from a catalogued provider.

## WSL2 networking (only relevant outside the cluster)

WSL2 NAT mode means `localhost` does not reach Windows services. Fixes are `networkingMode=mirrored` in `.wslconfig` (Windows 11 22H2+, then `wsl --shutdown`) or using the Windows host IP. Servers must bind `0.0.0.0` (`OLLAMA_HOST=0.0.0.0`). Inside k3s, Hermes uses Service DNS names instead.

## LiteLLM as the provider

The docs list LiteLLM proxy as a supported custom endpoint: run it on a port (4000 by default), then choose "Custom endpoint" with `http://<host>:4000/v1`. This matches the dsm-shai design.

## Not relevant here

The page also covers many cloud providers (Anthropic, OpenAI, Gemini, Bedrock, OpenRouter, Together, Groq and others). dsm-shai uses none of them, per the "no cloud model providers" constraint.
