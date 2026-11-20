# deploy/litellm

LiteLLM gateway (spec 09). Namespace `litellm`. Image `docker.io/litellm/litellm:1.109.1`, pinned by tag and digest. Postgres 16 alongside it for virtual keys. ClusterIP only, admin UI disabled (`DISABLE_ADMIN_UI=true`).

## Model aliases

| Alias | Backend | Notes |
|---|---|---|
| `chat` | `ollama_chat/qwen3.5:9b` | 256K native, 64K served by Ollama (see the Ollama README). Needs thinking on (`reasoning_effort` other than `none`), see `deploy/hermes/README.md`. Was `llama3.1:8b` until 2026-11-16 |
| `embed` | `ollama/nomic-embed-text:v1.5` | 768-dim |
| `vision` | `ollama_chat/qwen2.5vl:3b` | image input verified |

Endpoint: `http://litellm.litellm.svc:4000/v1`. No cloud providers, no fallbacks (`num_retries: 0`).

Aliases are roles, and they are changed in `config.yaml` through Git (the ConfigMap is hash-suffixed, so Flux rolls the gateway). Repoint an alias instead of adding a new name: each virtual key's model allowlist lives in the database, so a new name would need a manual `/key/update` on every consumer. Do not use the runtime `/model/new` API; it is not in Git.

## Secrets

`deploy/secrets/litellm.sops.yaml` (SOPS, age) holds `master-key` and `db-password` in Secret `litellm-secrets`. Flux decrypts it in the `secrets` stage. Nothing secret is in the ConfigMap or the manifests.

## Key provisioning (spec 09)

Virtual keys are created through the API with the master key. The admin UI is off.

```sh
# master key from the cluster (never commit it)
MK=$(kubectl -n litellm get secret litellm-secrets -o jsonpath='{.data.master-key}' | base64 -d)
curl -s -H "Authorization: Bearer $MK" -H 'Content-Type: application/json' \
  http://litellm.litellm.svc:4000/key/generate \
  -d '{"key_alias":"hermes","models":["chat","embed"],"max_budget":5.0,"rpm_limit":60}'
```

Per-key `models` is the allowlist; a request for another model returns 403 (verified with a throwaway key). `max_budget`, `rpm_limit` and `tpm_limit` are DB-backed and need Postgres. Revoke with `/key/delete`.

Consumer keys (`hermes`, `openviking`, `open-webui`) are issued when their consumer is deployed (steps 8 to 10). None are issued in step 7.

## Concurrency

- `chat` has `max_parallel_requests: 2` per deployment. A third concurrent call gets an immediate 429. Verified: two concurrent calls completed, the third was rejected in 0 s, with no model-swap thrash.
- Ollama runs `NUM_PARALLEL=1`, so the GPU work is serialised regardless.

## Timeouts and Ollama outage

- `chat` and `vision` use `timeout: 180` (covers a cold swap, a long prompt, and generation). `embed` uses 60 s. The cold-swap time for `llama3.1:8b` is about 4 s after a VLM eviction and about 40 s from a cold start.
- **Deviation:** an Ollama outage is not an instant failure. The `ollama` Service has no endpoints, and kube-proxy drops the SYN rather than rejecting it, so a raw TCP connect hangs for about 133 s. LiteLLM therefore fails after the total `timeout` (verified: a 60 s setting returned HTTP 408 after 60.6 s). With 180 s, the worst case is about 3 minutes. No fallback is attempted (verified in the log: `No fallback was attempted`). A proper fail-fast needs a REJECT rule or a readiness-gated connect, which is outside this spec.

## Metrics (spec 06)

`/metrics/` on port 4000. `require_auth_for_metrics_endpoint: false` so the in-cluster Prometheus can scrape without a credential. The metrics carry hashed key and alias labels, never prompts or keys. Spec 08 will restrict this endpoint to the `monitoring` namespace. Labels verified: `hashed_api_key`, `api_key_alias`, `requested_model`, `model_id`, `status_code`. ServiceMonitor `litellm` is `up` in Prometheus.

## Logging

`turn_off_message_logging: true`. Prompt and response content is not logged. Enabling it is an explicit opt-in change to `config.yaml`.

## Not yet done (later steps)

- **MCP gateway registrations** (OpenViking MCP and the browser MCP server, `deploy/browser/`): not in this step. The browser pod, its allowlists and the MCP tool-allowlist test belong with the Hermes step (4 of spec 04) and spec 08.
- Hermes, OpenViking and Open WebUI repointing and their virtual keys: steps 8 to 10.
- Istio AuthorizationPolicy denying direct Ollama access: step 11 (spec 08 part B).
- Postgres backup and restore: step 13 (spec 07 part B).
- Secret scan of Git: pending the pre-commit and CI scanning in step 2.

## MCP gateway (spec 09)

Registered on 2026-11-16: the OpenViking MCP server, via `POST /v1/mcp/server` (the registration lives in the LiteLLM database, which is in the restic backup). It is not in `config.yaml`: this LiteLLM release resolves `${NAME}` header values only from database env vars, and a literal header in YAML would put the credential in git.

- **Server:** `openviking`, `http://openviking.openviking.svc:1933/mcp`, transport `http`, auth `api_key`. The credential is the Hermes OpenViking tenant key, so the gateway and Hermes share one memory tenant. A second consumer needs its own server entry with its own tenant key.
- **Server tool allowlist:** all 31 OpenViking tools (`allowed_tools`). An empty list means no tools, which is how the first registration failed.
- **Per-key allowlist:** a key reaches a server only if `object_permission.mcp_servers` lists it. Verified: the `hermes` key gets 403 for `openviking` until it is granted, then tools list with status `ok`. Grant with `POST /key/update` and `{"key_alias":"hermes","object_permission":{"mcp_servers":["openviking"]}}`.
- **Mesh:** `openviking-from-hermes` also allows the LiteLLM identity on port 1933.
- **Per-server route:** `POST /openviking/mcp` on port 4000. The aggregate `/mcp/` route returned no tools for the master key.

Hermes does **not** use this route yet. Routed through the gateway, the OpenViking tools were deferred behind a bridge, and llama3.1:8b did not call them reliably (recall failed). Hermes uses the direct OpenViking route, which passed recall. Revisit when the model can call deferred tools reliably.

## Egress policy (spec 12 follow-up)

`egress-networkpolicy.yaml` limits LiteLLM to DNS, Ollama (11434), its Postgres (5432) and the ambient HBONE tunnel (15008). Postgres may reach DNS and HBONE only. LiteLLM has no route to the public internet, so no cloud provider can be configured in it by accident. To test it, make a real HTTPS request from the pod; a plain TCP connect always succeeds in ambient mode (the redirect to ztunnel accepts it), so it proves nothing.


## Ministral tool-call hook (2026-11-20)

`ministral_tools.py` is mounted at `/app/ministral_tools.py` and loaded with `litellm_settings.callbacks: ministral_tools.handler`. Ollama 0.40.16 returns Ministral 3's tool calls as text (`name[ARGS]{json}`); the hook rewrites a non-streamed reply that is only such calls, for tools named in the request, into structured `tool_calls` and sets `finish_reason: tool_calls`. It never raises and leaves everything else alone. It does not run on streamed replies, so Hermes uses `streaming: false`. Tests: `make test` (`deploy/litellm/tests`). Remove it when Ollama parses the format natively.
