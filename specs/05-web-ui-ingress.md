# Spec 05 — Web UI Ingress

**Status:** TODO

## Purpose

Deploy Open WebUI as the human-facing chat front end in its own `open-webui` namespace, backed by the in-cluster LiteLLM gateway (spec 09), which fronts Ollama (spec 02). Expose it to the local machine only, through the Istio ingress gateway (spec 08), with authentication enabled and data persisted.

## Behavior

- Open WebUI runs in namespace `open-webui` as a single-replica Deployment (or StatefulSet) pinned to a specific image tag, never `latest`. Manifests live in `deploy/open-webui/`.
- Open WebUI's OpenAI-compatible connection is set by environment (`OPENAI_API_BASE_URL=http://litellm.litellm.svc:4000/v1`, `OPENAI_API_KEY` from the `open-webui` LiteLLM virtual key, spec 09, SOPS-managed per spec 07). Never the LiteLLM master key. `ENABLE_OLLAMA_API=False` disables the direct Ollama connection (and `K8S_FLAG` is left unset), `ENABLE_OPENAI_API_PASSTHROUGH` stays `False`, and no external model or API endpoints are configured.
- `ENABLE_PERSISTENT_CONFIG=False`, so environment variables win on every restart. Otherwise connection, signup and search settings are stored in the database on first boot and later manifest changes (including Flux-driven ones, spec 10) are silently ignored. Admin UI edits to those settings are therefore lost on restart, which is intended.
- `TASK_MODEL_EXTERNAL` points at the `chat` alias (or a smaller alias) so titles and search queries do not force extra model swaps on the 16GB GPU. Tools and Functions are disabled with `ENABLE_PLUGINS=false` unless needed.
- Use the `:slim` image variant (pinned tag and digest) and route RAG embeddings through LiteLLM (`RAG_EMBEDDING_ENGINE=openai`, `RAG_OPENAI_API_BASE_URL`, `RAG_EMBEDDING_MODEL=embed`) rather than loading CPU embedding models in the pod.
- Open WebUI's data directory is mounted from a PVC on the k3s `local-path` storage class. This storage must live on the WSL ext4 volume, not under `/mnt/c`.
- Authentication is enabled (`WEBUI_AUTH=True`, which is never turned off, since disabling it is irreversible). The admin account is pre-seeded from a Secret (`WEBUI_ADMIN_EMAIL`, `WEBUI_ADMIN_PASSWORD`, which apply only when no users exist and disable signup), and `ENABLE_SIGNUP=False` stays set.
- `WEBUI_SECRET_KEY` is an explicit value delivered through a Kubernetes Secret, managed per the secrets approach in spec 07. If left to auto-generate it lives outside the data volume and is lost on pod recreation, which invalidates sessions and encrypted data. No secret value appears in manifests, ConfigMaps, logs or git history.
- Set `WEBUI_URL` and `CORS_ALLOW_ORIGIN` to the ingress origin (a mismatch breaks WebSocket and streaming with JSON parse errors), and `FORWARDED_ALLOW_IPS` to the gateway only. The cookie settings are `WEBUI_SESSION_COOKIE_SAME_SITE=strict`, and `WEBUI_SESSION_COOKIE_SECURE=true` once TLS is on.
- Open WebUI gets a ClusterIP Service and an Istio `Gateway` + `HTTPRoute` (or `VirtualService`) on the ingress gateway from spec 08. The gateway's listener must be reachable from Windows via `localhost` / WSL2 port forwarding.
- The ingress host rule is `open-webui.localhost`, or a hosts-file name if the user prefers. A plain `localhost` path works as a fallback. The route passes WebSocket `Upgrade`/`Connection` headers, keeps response buffering off (SSE) and uses read timeouts of at least 300s, consistent with spec 08.
- Storage is SQLite on the PVC, so the Deployment is a single replica with `strategy: Recreate` and `UVICORN_WORKERS=1`. The PVC is prune-exempt under Flux (spec 10).
- Exposure is host-local only. The ingress gateway is not bound to a LAN or public interface, and no `NodePort` or `hostPort` is created for any workload in this spec. The gateway's own Service is the only exception.
- Rule: Ollama, OpenViking, LiteLLM and Hermes stay `ClusterIP`-only and must never be referenced by any Ingress, HTTPRoute or VirtualService. Open WebUI and Grafana (spec 06) are the only workloads exposed through the ingress gateway.
- Istio AuthorizationPolicies (spec 08) in `open-webui` default-deny. Egress is allowed only to LiteLLM (port 4000), cluster DNS (kube-dns, UDP/TCP 53), and SearXNG if enabled. A baseline default-deny NetworkPolicy remains as defense-in-depth.
- Ingress to Open WebUI is allowed only from the Istio ingress gateway.
- Liveness and readiness probes plus modest resource requests and limits are set, so the pod doesn't starve Ollama.
- **Optional decision point: SearXNG web search.**
  - Decision: enable it or skip it. The default is skip.
  - If enabled, SearXNG runs as a ClusterIP-only Deployment, in `open-webui` or its own namespace.
  - SearXNG must enable JSON output (`json` under `search.formats` in `settings.yml`) or Open WebUI gets 403, and its bot limiter is disabled for in-cluster callers. It runs with only the `CHOWN SETGID SETUID DAC_OVERRIDE` capabilities. Open WebUI's web search is configured to use it (`ENABLE_WEB_SEARCH=True`, `WEB_SEARCH_ENGINE=searxng`, `SEARXNG_QUERY_URL`), and Hermes may also use it as a search backend (this requires a matching egress allowance in spec 04's Istio policy).
  - The Open WebUI egress policy gains a single rule to SearXNG.
  - SearXNG's own egress to public search engines is a documented, explicit exception. It is never exposed through the ingress.
  - `WEB_LOADER_ENGINE=playwright` is not used. The sandboxed browser MCP pod (spec 09) is the only browser, and `ENABLE_RAG_LOCAL_WEB_FETCH=false` blocks fetches to private ranges.
  - If skipped, no SearXNG resources exist, and the base spec is still complete.

## Acceptance Criteria

- [ ] `kubectl get ns open-webui` succeeds, and the Open WebUI pod reaches `Ready`.
- [ ] The image tag is pinned and the manifests contain no plaintext secret values.
- [ ] `WEBUI_SECRET_KEY` comes from a Kubernetes Secret created per the secrets approach in spec 07, and sessions survive deleting the pod.
- [ ] Changing a ConfigVar-type env value (for example `ENABLE_SIGNUP`) in git and reconciling takes effect after a restart (`ENABLE_PERSISTENT_CONFIG=False`).
- [ ] A PVC is `Bound` on the ext4-backed storage class. Chat history and the user account survive a pod restart.
- [ ] From Windows, `http://open-webui.localhost` (or the chosen name) loads the Open WebUI login page through the Istio ingress gateway.
- [ ] The pre-seeded admin can log in, and the signup route and API are rejected.
- [ ] A chat in the UI returns a completion, via LiteLLM using the `open-webui` key (not the master key), from a model served by in-cluster Ollama, and tokens stream incrementally through the gateway.
- [ ] No Ingress, HTTPRoute or VirtualService targets Ollama, OpenViking, LiteLLM or Hermes, and their Services are of type `ClusterIP`.
- [ ] No `NodePort`, `LoadBalancer` or `hostPort` exists for Open WebUI, Ollama, OpenViking or Hermes.
- [ ] The service is unreachable from another LAN host, which is verified by a connection attempt to the WSL IP and Windows host IP from a second device.
- [ ] From the Open WebUI pod, a connection to LiteLLM and a DNS lookup succeed. A connection to Ollama directly, an arbitrary external IP or other in-cluster services (for example OpenViking or Hermes) is blocked.
- [ ] If SearXNG is enabled, a web search from the UI succeeds, and a direct Open WebUI connection to anything other than LiteLLM, DNS or SearXNG remains blocked.
- [ ] If SearXNG is skipped, the acceptance criteria above pass without any SearXNG resources.
- [ ] `deploy/open-webui/README.md` documents setup and teardown steps, the chosen hostname and the SearXNG decision.
