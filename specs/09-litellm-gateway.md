# Spec 09 — LiteLLM Gateway

**Status:** PARTIAL (gateway, keys, metrics verified; MCP/browser registration, consumer integrations, Istio deny and backup pending; see deploy/litellm/README.md)

> **Amendment (2026-11-16):** the `chat` alias routes to `ollama_chat/qwen3.5:9b` (thinking on), not `qwen3:14b` or `llama3.1:8b` (see the spec 02 and spec 04 amendments).

> **Amendment (2026-11-17, spec 11):** Hermes also holds an optional `GITHUB_TOKEN` (for the nightly specter job). It is not a model credential and does not go through LiteLLM.

## Purpose
Deploy the free open-source LiteLLM proxy (no enterprise-licensed features) in its own k3s namespace `litellm` as the single routing gateway for models, MCP tools, and browser automation between all consumers and backends. Depends on specs 01, 02, 03, 04, 05, 07, 08.

## Behavior

**Deployment**
- Namespace `litellm`; official LiteLLM image pinned by tag and digest; config in a ConfigMap (`config.yaml`); liveness/readiness probes; CPU/memory requests and limits; ClusterIP Service only. Manifests live in `deploy/litellm/`.
- Admin UI is disabled by default. If enabled, it is reachable only host-local or via the spec 08 ingress.
- Only open-source features are used. `deploy/litellm/README.md` lists which features need the DB: virtual keys, per-key budgets, and spend tracking.

**Model routing**
- One OpenAI-compatible endpoint at `http://litellm.litellm.svc:4000/v1` with stable aliases: `chat` (qwen3:14b), `embed` (nomic-embed-text), `vision` (qwen2.5vl:3b), mapped to the in-cluster Ollama from spec 02.
- Hermes (spec 04), OpenViking (spec 03) and Open WebUI (spec 05) are repointed to LiteLLM. Ollama accepts traffic only from LiteLLM, enforced by an Istio AuthorizationPolicy (spec 08).
- Only one chat model fits the 16GB VRAM budget, so config stays simple:
  - No cloud fallbacks (everything local, per CLAUDE.md).
  - `num_retries: 0` for generations.
  - Request timeouts long enough for cold model swaps.
  - Streaming passthrough.
  - A concurrency/queue limit so parallel agent requests do not thrash model swaps.

**MCP gateway and browser routing**
- Use LiteLLM's built-in MCP gateway to register in-cluster MCP servers, giving Hermes one MCP endpoint with per-key tool allowlists:
  - OpenViking's MCP endpoint (spec 03), if supported. If it is not, document the gap and the workaround.
  - A headless Playwright MCP server in its own namespace and pod (`deploy/browser/`).
- **Assumption (flag for user confirmation):** "model/mcp/browser routing" is interpreted as routing browser automation through an MCP browser tool, not a separate browser-proxy product.
- The browser pod handles arbitrary web content and is high-risk:
  - Non-root user, no privilege escalation, all capabilities dropped, no host mounts, and CPU/memory limits.
  - Ephemeral profile storage (`emptyDir`, size-limited).
  - Egress only through the spec 08 Istio egress allowlist, with default-deny NetworkPolicy/AuthorizationPolicy.
  - Reachable only from LiteLLM.

**Auth and data**
- The master key and the virtual keys (`hermes`, `openviking`, `open-webui`) are delivered as SOPS-managed Secrets (spec 07). No keys appear in the ConfigMap, manifests, or logs.
- Each virtual key has its own model allowlist, MCP tool allowlist, budget, and rate limit. Only `hermes` gets browser tools.
- Requests with a missing or invalid key are rejected.
- Postgres runs as a small single-instance StatefulSet with a PVC on WSL ext4 (not `/mnt/c`), with credentials in a SOPS Secret and the data included in the spec 07 backup scope.

**Observability**
- The Prometheus metrics endpoint (request counts, latency, token usage per key and model) is scraped by spec 06.
- Request logging keeps prompt and response content OFF by default. Enabling it is an explicit, documented opt-in.

## Acceptance Criteria
- [x] Namespace `litellm` has LiteLLM and Postgres pods Ready. The image reference includes a pinned tag and digest, and the Service is ClusterIP only.
- [x] `chat`, `embed`, and `vision` requests through `litellm.litellm.svc:4000/v1` succeed. Chat streams correctly.
- [ ] Hermes, OpenViking, and Open WebUI work end to end using LiteLLM with their own virtual keys, with no direct Ollama URLs in their configs.
- [ ] A direct request from the hermes pod to Ollama is denied by Istio, and the same request from LiteLLM succeeds.
- [x] A request with a missing or wrong key returns 401. A key requesting a model outside its allowlist is rejected.
- [ ] An MCP tool call through the gateway succeeds against OpenViking. A key without the tool allowlist is denied.
- [x] Two concurrent `chat` requests are queued or limited without a model-swap thrash, and a cold-swap request completes without timing out.
- [ ] No cloud provider is configured, and no fallback is triggered when Ollama is down (the request behaviour is bounded by the 180 s timeout). No cloud provider and no fallback are verified; an outage is bounded by the 180 s timeout (see deploy/litellm/README.md).
- [x] LiteLLM metrics appear in Prometheus (spec 06) with per-key and per-model labels. Logs contain no prompt or response content by default.
- [ ] A secret scan finds no master key, virtual key, or DB password in Git. A Postgres backup and restore (spec 07) preserves virtual keys.
- [ ] `deploy/litellm/README.md` documents the model aliases, key provisioning, MCP server registration and the DB-dependent features.
