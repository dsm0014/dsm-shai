# LiteLLM Proxy: Deployment, Ollama Routing, Keys, Timeouts, Metrics

**Tags:** litellm, gateway, ollama, virtual-keys, postgres, prometheus, kubernetes, spec-09

Source: docs.litellm.ai (the requested `/docs/simple_proxy` is only a landing page, so this follows its links: ollama provider, virtual_keys, docker_quick_start, deploy/helm, prod, timeout, reliability, prometheus). Content came through a summarizing fetch, and version-specific details (v1.85.0, v1.101.0, chart 1.0.0) should be re-checked against the pinned image.

## Model routing to Ollama

```yaml
model_list:
  - model_name: chat            # stable alias used by clients
    litellm_params:
      model: ollama_chat/qwen3:14b
      api_base: http://ollama.ollama.svc:11434
      keep_alive: "10m"
    model_info: {supports_function_calling: true}
```
- `ollama_chat/<model>` uses `/api/chat` (recommended for chat). `ollama/<model>` uses `/api/generate`.
- `keep_alive` is passed to Ollama (`"8m"`, or `-1` for forever). Embeddings and `num_ctx` handling were not covered by the fetched summary. Verify against the provider page when implementing the `embed` and `vision` aliases.
- Alias names (`chat`, `embed`, `vision`) in `model_name` are what spec 09 requires, hiding the Ollama tags from clients.

## Auth, keys and the database

- Virtual keys, per-key budgets (`max_budget`, `budget_duration`), `rpm_limit`, `tpm_limit`, `duration`, a per-key `models` allowlist and spend tracking all require **Postgres** (`DATABASE_URL=postgresql://user:pass@host:5432/db`). Without a DB only the static master key works. This matches spec 09's "DB-dependent features" list.
- Master key must start with `sk-` (`LITELLM_MASTER_KEY` or `general_settings.master_key`). `LITELLM_SALT_KEY` encrypts stored credentials and **must not change** after models or keys are stored, so back it up with the other secrets (spec 07).
- Create a key: `POST /key/generate` with `Authorization: Bearer <master>` and a body such as `{"key_alias":"hermes","models":["chat","embed"],"rpm_limit":..,"max_budget":..}`.
- Redis is only needed for multi-replica shared state. Single-instance dsm-shai does not need it. The upstream Helm chart expects both Postgres and Redis to exist already and has a gateway/backend/ui split with HPA, so plain manifests (or a minimal values file) fit a single-node cluster better.

## Deployment facts

- Image: `docker.litellm.ai/berriai/litellm:<tag>`. Pin by digest. Config is mounted at `/app/config.yaml` and started with `--config /app/config.yaml`, listening on port 4000.
- Probes: `/health/readiness` and `/health/liveness` on port 4000 (the upstream example uses `initialDelaySeconds: 120`).
- Single worker per pod on Kubernetes (`--num_workers 1`). Upstream suggests about 1 CPU and 4Gi per worker at scale. Size down for a single user, and cap with limits.
- Production env: `LITELLM_MODE=PRODUCTION`, `LITELLM_LOG=ERROR`, `litellm_settings.json_logs: true`, `general_settings.disable_error_logs: true`.
- Read-only root filesystem needs writable paths via `LITELLM_MIGRATION_DIR`, `LITELLM_UI_PATH`, `LITELLM_ASSETS_PATH`, `PRISMA_BINARY_CACHE_DIR`, `XDG_CACHE_HOME`. The image can run as non-root (uid 101 in the docs).
- `store_model_in_db: true` lets the UI/API manage models and MCP servers. For GitOps-style config, leave it false and keep everything in the ConfigMap, except per-key MCP grants (see [[litellm-mcp-gateway]]).
- Admin UI is optional and tied to the DB. Spec 09 disables it by default.

## Timeouts, retries and fallbacks (the Ollama cold-swap issue)

```yaml
litellm_settings:
  request_timeout: 600
  num_retries: 0          # never duplicate a generation
  # no fallbacks / default_fallbacks (no cloud models)
  sse_keepalive_ping_interval_seconds: 15
model_list:
  - model_name: chat
    litellm_params: {timeout: 600, stream_timeout: 120}
```
- `timeout` is for the full response, and `stream_timeout` is for the first streamed chunk. Both must exceed a cold Ollama model load.
- Retries happen per `model_name` before fallbacks, so `num_retries: 0` plus no `fallbacks` gives fail-fast behaviour. Router cooldowns (`allowed_fails`, `cooldown_time`) apply to deployments, so keep them lenient with a single deployment.
- The page showed `mock_timeout: true` in a request body as a way to test timeout and retry behaviour.

## Metrics

- Enable with `litellm_settings.callbacks: ["prometheus"]`. This is open-source (only managed-batch metrics are enterprise).
- `/metrics` requires auth by default (v1.85.0+). Scrape with `Authorization: Bearer sk-...`, or set `require_auth_for_metrics_endpoint: false`, which is acceptable only if the mesh restricts callers. A dedicated unauthenticated port is available via `--prometheus_metrics_port` (v1.101+).
- Useful families: `litellm_proxy_total_requests_metric`, `litellm_proxy_failed_requests_metric`, `litellm_total_tokens_metric`, `litellm_input_tokens_metric`/`litellm_output_tokens_metric`, `litellm_spend_metric`, `litellm_request_total_latency_metric`, `litellm_llm_api_latency_metric`, `litellm_llm_api_time_to_first_token_metric`, `litellm_request_queue_time_seconds`, `litellm_in_flight_requests`, `litellm_deployment_*` (state, cooldown, fallbacks), `litellm_mcp_tool_calls_total`. Labels include `hashed_api_key`, `api_key_alias`, `model`, `team`, `requested_model`.
- Cardinality controls: `prometheus_metrics_config` (`include_labels`), `prometheus_exclude_metrics`, `prometheus_exclude_labels`, `prometheus_metrics_max_series_per_metric`, `prometheus_metrics_ttl_seconds`. Multi-worker setups need `PROMETHEUS_MULTIPROC_DIR`.

## Gotchas

- The upstream docs advertise guardrails, SSO and a team/org hierarchy. Some are enterprise-gated, so check the feature page's licence note before enabling anything beyond keys, budgets, rate limits and metrics.
- Prompt and response logging is a callback choice. Leave content logging off (spec 09 requirement).
