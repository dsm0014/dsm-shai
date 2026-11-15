# OpenViking: Embedding/VLM Providers with Ollama, and MCP Endpoint

**Tags:** openviking, ollama, embeddings, vlm, mcp, litellm, spec-03, spec-09

Source: github.com/volcengine/OpenViking (`docs/en/guides/01-configuration.md`, `06-mcp-integration.md`, `openviking_cli/setup_wizard.py`, `utils/ollama.py`, `bootstrap.py`).

## Providers

- **Embedding** (`embedding.dense.provider`): `openai`, `azure`, `volcengine`, `vikingdb`, `jina`, `ollama`, `gemini`, `voyage`, `dashscope`, `minimax`, `cohere`, `litellm`, `local`. Ollama, OpenAI-compatible and local are **dense only** (sparse and hybrid need volcengine or vikingdb). Fields: `dimension`, `input` (`text`|`multimodal`), `batch_size`, `max_concurrent` (10), `max_retries` (3), `max_input_tokens` (4096), `circuit_breaker`.
- **VLM** (`vlm.provider`): `volcengine`, `openai` (OpenAI-compatible chat completions), `openai-codex`, `kimi`, `glm`, `litellm`. Fields include `model`, `api_base`, `api_key`, `temperature`, `max_concurrent` (32), `max_retries` (3), `timeout` (default 600s), `extra_request_body`.
- **Vector dimension is fixed when the index is created.** Changing the embedding model or dimension later requires a reindex. `litellm` embeddings require `dimension` to be set explicitly.
- If the VLM is unavailable, summaries and overviews come out empty or "not ready", so the VLM is not optional.

## Config the setup wizard writes for local Ollama

```json
{
  "embedding": {"dense": {"provider": "ollama", "model": "qwen3-embedding:0.6b",
                          "api_base": "http://localhost:11434/v1", "dimension": 1024, "input": "text"}},
  "vlm": {"provider": "litellm", "model": "ollama/qwen3.5:4b", "api_key": "no-key",
          "api_base": "http://localhost:11434", "temperature": 0.0, "max_retries": 2,
          "extra_request_body": {"num_ctx": 16384, "think": false}}
}
```
- Embedding `api_base` includes `/v1`. The litellm-provider VLM `api_base` does **not**.
- `num_ctx: 16384` matters. The memory-extraction prompt is about 5k tokens and Ollama's 4096 default silently truncates it. `think: false` is required for thinking models, or they emit only reasoning.
- Wizard presets: embeddings `qwen3-embedding:0.6b/4b/8b` (1024 dims) and `embeddinggemma:300m` (768). VLM presets `qwen3.5:4b/9b`, `gemma4:*` etc. By RAM tier, 16GB or less picks `qwen3-embedding:0.6b` + `qwen3.5:4b`. A litellm example in the code comments uses `ollama/nomic-embed-text` at dimension 768.
- Optional third model: a local query planner (`guoxuter/ov_intent_analysis_sft:v7_q8`) via a `query_planner` block. Not needed for the dsm-shai VRAM budget.
- The server never runs `ollama pull`, so models must be pulled first (init Job or Ollama startup script).
- `bootstrap.py` does an Ollama preflight at startup (`GET /api/tags` for remote hosts), which only warns on failure, while `/ready` repeats it on every call.

## Applying to dsm-shai (via LiteLLM, spec 09)

- Both calls should go to the LiteLLM aliases rather than Ollama: `embedding.dense.provider: openai` (or `litellm`) with `api_base: http://litellm.litellm.svc:4000/v1`, `model: embed`, `dimension: 768` (`nomic-embed-text`) and `api_key: ${OPENVIKING_LITELLM_KEY}`. VLM: `provider: openai`, `model: vision` (qwen2.5vl:3b) via the same base URL.
- `extra_request_body` (`num_ctx`, `think`) is passed to the backend. Whether LiteLLM forwards it to Ollama must be tested, and alternatively `num_ctx` can be set in the LiteLLM `litellm_params` or Ollama defaults (32k context is already the server default).
- The VLM must handle the 5k-token extraction prompt at the Ollama context size (32k) and swap in and out of VRAM (the chat and vision models are not co-resident). Raise `vlm.timeout` above the cold-swap time.
- Choose `nomic-embed-text` (768 dims) deliberately and lock `dimension` in config before the first ingest to avoid a reindex.

## MCP endpoint

- Streamable HTTP MCP at `http://<server>:1933/mcp`, sharing the REST port and auth. In `api_key` mode send `X-Api-Key: <user key>` or `Authorization: Bearer <key>` (a **user or admin key**, not the root key).
- Tools: `find`, `search`, `rule_search`, `read`, `write`, `edit`, `list`, `tree`, `grep`, `glob`, `forget`, `remember`, `add_resource`, `add_skill`, `download`, `list_watches`, `cancel_watch`, `health`, `privacy_*`, `list_users`, `list_groups`, `get_acl`, `set_acl`, `find_mcp_tools`, `invoke_mcp_tool`.
- Local file uploads through `add_resource` return a one-shot upload URL (`POST /api/v1/resources/temp_upload?token=...`) held in-process, which is another reason for a single worker. `download` returns a similar URL. Behind a proxy, set `public_base_url` so these URLs are correct.
- Claude Code example: `claude mcp add --transport http openviking <url>/mcp --header "Authorization: Bearer KEY"`. Claude.ai and Desktop use OAuth 2.1, which is not needed here.
- This resolves the spec 03/09 open question: **OpenViking does support MCP.** Register `http://openviking.openviking.svc:1933/mcp` in LiteLLM's `mcp_servers` with a bearer token for an OpenViking user key (see [[litellm-mcp-gateway]]), and use `allowed_tools` to expose only read/search tools (and `remember` if the agent should write memory) to Hermes.
