# Open WebUI: Config, LiteLLM Connection, Auth and Persistence

**Tags:** open-webui, litellm, auth, persistent-config, kubernetes, ingress, spec-05

Source: docs.openwebui.com (home, quick start, OpenAI-compatible providers, `reference/env-configuration`, Kubernetes, HTTPS, Hardening). Env-var details come from the docs repo MDX source. The Kubernetes and Hardening pages came through a summarizing fetch, so verify manifest values against the live pages. Some older doc paths (for example `/getting-started/env-configuration`) now 404.

## Connect to LiteLLM (OpenAI-compatible)

- Env form: `OPENAI_API_BASE_URL=http://litellm.litellm.svc:4000/v1`, `OPENAI_API_KEY=<open-webui virtual key>`. Disable the direct Ollama connection with `ENABLE_OLLAMA_API=False`. `OLLAMA_BASE_URL` defaults to an in-cluster Service URL when `K8S_FLAG` is set, so set the flag off or disable the API explicitly.
- Admin UI alternative: Settings > Connections > OpenAI-compatible. "Verify Connection" calls `GET <url>/models`. The Provider dropdown can be left at Default (or `LiteLLM`, which only matters for Anthropic Messages endpoint passthrough).
- Required backend endpoint: `/v1/chat/completions`. `/v1/models` is recommended. Embeddings, audio and images are optional.
- **Use a least-privilege per-consumer key, never the LiteLLM master key** (the docs call this out explicitly for LiteLLM). This matches spec 09's `open-webui` virtual key with a model allowlist.
- `TASK_MODEL_EXTERNAL` sets the model used for titles and search queries. Point it at the `chat` alias, or a smaller alias to avoid extra swaps on a 16GB GPU.
- `ENABLE_OPENAI_API_PASSTHROUGH` must stay `False` (default). When on, it forwards arbitrary requests upstream without model access control.
- `AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST` (default 10s) may need raising if LiteLLM is slow at startup.

## Persistent config trap

Variables marked ConfigVar (including `OPENAI_*`, `ENABLE_SIGNUP`, `WEB_SEARCH_*`, `SEARXNG_*`, `ENABLE_OLLAMA_API`, `WEBUI_URL`) are stored in the database on first launch and then take precedence over the environment. Later manifest changes are silently ignored. For GitOps-managed config set `ENABLE_PERSISTENT_CONFIG=False`, so env vars win on every restart. This is the right default for dsm-shai, but note that Admin UI edits will then be lost on restart.

## Auth and secrets

- `WEBUI_SECRET_KEY`: set an explicit value from a Secret (`openssl rand -hex 32`). If it is left to auto-generate it is stored in `/app/backend/.webui_secret_key`, **outside** the data volume, so it is lost on pod recreation. That invalidates sessions and breaks encrypted data (MCP/OAuth tokens). It must be identical across replicas.
- First registered user becomes admin. Pre-seed with `WEBUI_ADMIN_EMAIL` + `WEBUI_ADMIN_PASSWORD` (+ `WEBUI_ADMIN_NAME`) from a Secret. These apply only when no users exist and automatically disable sign-up.
- `ENABLE_SIGNUP=False` after creating the admin. `DEFAULT_USER_ROLE=pending` (default) if sign-up stays on. `WEBUI_AUTH=False` (single-user, no login) works only on a fresh install and is irreversible, so avoid it.
- `ENABLE_LOGIN_FORM=False` also blocks local sign-ups. Only use it with SSO set up.
- On HTTPS: `WEBUI_SESSION_COOKIE_SECURE=true`, `WEBUI_SESSION_COOKIE_SAME_SITE=strict`. `JWT_EXPIRES_IN` defaults to `4w`.
- Open WebUI does not terminate TLS and must sit behind an authenticated or private entry point.
- `ENABLE_PLUGINS=false` disables Tools and Functions (arbitrary Python) if unused.

## Data and storage

- `DATA_DIR` is `/app/backend/data` in the image: SQLite DB, uploads, plugins, vector DB. Mount a PVC there on the WSL ext4 `local-path` volume. SQLite means single replica (`strategy: Recreate`, `UVICORN_WORKERS=1`). More replicas need PostgreSQL (`DATABASE_URL`), Redis (`WEBSOCKET_MANAGER=redis`, `REDIS_URL`) and the same secret key, which is out of scope here.
- Image variants: `:main` (about 1.6GB, bundles embedding/speech models), `:slim` (about 200MB, API-only). Prefer pinning a tag and digest, as spec 05 requires. Consider `:slim`, so RAG embeddings go through LiteLLM (`RAG_EMBEDDING_ENGINE=openai`, `RAG_OPENAI_API_BASE_URL`, `RAG_EMBEDDING_MODEL=embed`) instead of CPU models in the pod.

## Helm chart (optional path)

Official chart `open-webui/open-webui` (the docs show chart 18.0.0 for app v0.13.0) accepts `openaiBaseApiUrl`, `openaiApiKeyExistingSecret(+Key)`, `ollama.enabled=false`, `pipelines.enabled=false`, `persistence.*` (with `helm.sh/resource-policy: keep`), probes `/health` and `/ready`, and `extraEnvVars`. Suggested sizing from the docs: requests 500m CPU / 1Gi, limits 2 CPU / 4Gi, and `strategy: Recreate`. Kustomize manifests are equally valid under spec 05's `deploy/` convention.

## Ingress and streaming

- `WEBUI_URL` = the public URL (needed for OAuth, and set early since it is persisted). `CORS_ALLOW_ORIGIN` must match the origin, or WebSocket and streaming fail with odd JSON errors (`Unexpected token 'd', "data: {"id"..."`).
- The proxy must pass WebSocket `Upgrade`/`Connection` headers, **disable response buffering** (SSE streaming breaks markdown rendering) and use read timeouts of at least 300s. This aligns with the spec 08 gateway route settings.
- `FORWARDED_ALLOW_IPS` defaults to `*`. Restrict it to the gateway.

## Web search with SearXNG (optional)

- Settings: `ENABLE_WEB_SEARCH=True`, `WEB_SEARCH_ENGINE=searxng`, `SEARXNG_QUERY_URL=http://searxng.<ns>.svc:8080/search`, `WEB_SEARCH_RESULT_COUNT=3`, `WEB_SEARCH_CONCURRENT_REQUESTS` (0 = unlimited, 1 avoids rate limits), `WEB_LOADER_CONCURRENT_REQUESTS` (10).
- **SearXNG must enable JSON output**, or Open WebUI gets `403 Forbidden`: add `json` under `search.formats` in `settings.yml` (the docs add `html` and `json`). Disable the bot limiter for in-cluster callers (`limiter.toml`: `link_token = false`). The docs mark the SearXNG page as community-contributed.
- Container: `searxng/searxng`, config at `/etc/searxng`, port 8080, capabilities `CHOWN SETGID SETUID DAC_OVERRIDE` only (drop the rest).
- Egress: page fetches and SearXNG upstream engines need outbound access, so the mesh egress allowlist (spec 08) must include whatever hosts are used, or search is limited to what is allowlisted. `WEB_FETCH_FILTER_LIST` and `ENABLE_RAG_LOCAL_WEB_FETCH=false` block SSRF to private ranges by default.
- `WEB_LOADER_ENGINE=playwright` would install Chromium inside the Open WebUI container unless `PLAYWRIGHT_WS_URL` points at a remote browser. Do not use it (spec 09 has the sandboxed browser pod).
