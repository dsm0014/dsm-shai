# Spec 05 — Web UI Ingress

**Status:** PARTIAL (deployed, ingress login and chat verified; mesh deny/egress checks and the LAN and Windows checks pending; see deploy/open-webui/README.md)

## Purpose

Deploy Open WebUI as the human-facing chat front end in its own `open-webui` namespace, backed by the in-cluster LiteLLM gateway (spec 09), which fronts Ollama (spec 02). Expose it to the local machine only, through the Istio ingress gateway (spec 08), with authentication enabled and data persisted.

## Behavior

- Open WebUI runs in namespace `open-webui` as a single-replica Deployment (or StatefulSet) pinned to a specific image tag, never `latest`. Manifests live in `deploy/open-webui/`.
- Open WebUI's OpenAI-compatible connection points at `http://litellm.litellm.svc:4000/v1` using the `open-webui` LiteLLM virtual key (spec 09, SOPS-managed per spec 07). The direct Ollama connection is disabled, and no external model or API endpoints are configured.
- Open WebUI's data directory is mounted from a PVC on the k3s `local-path` storage class. This storage must live on the WSL ext4 volume, not under `/mnt/c`.
- Authentication is enabled (`WEBUI_AUTH=True`). The first account created becomes admin, and then signup is disabled (`ENABLE_SIGNUP=False`) and stays disabled.
- `WEBUI_SECRET_KEY` is delivered through a Kubernetes Secret, managed per the secrets approach in spec 07. No secret value appears in manifests, ConfigMaps, logs or git history.
- Open WebUI gets a ClusterIP Service and an Istio `Gateway` + `HTTPRoute` (or `VirtualService`) on the ingress gateway from spec 08. The gateway's listener must be reachable from Windows via `localhost` / WSL2 port forwarding.
- The ingress host rule is `open-webui.localhost`, or a hosts-file name if the user prefers. A plain `localhost` path works as a fallback.
- Exposure is host-local only. The ingress gateway is not bound to a LAN or public interface, and no `NodePort` or `hostPort` is created for any workload in this spec. The gateway's own Service is the only exception.
- Rule: Ollama, OpenViking, LiteLLM and Hermes stay `ClusterIP`-only and must never be referenced by any Ingress, HTTPRoute or VirtualService. Open WebUI and Grafana (spec 06) are the only workloads exposed through the ingress gateway.
- Istio AuthorizationPolicies (spec 08) in `open-webui` default-deny. Egress is allowed only to LiteLLM (port 4000), cluster DNS (kube-dns, UDP/TCP 53), and SearXNG if enabled. A baseline default-deny NetworkPolicy remains as defense-in-depth.
- Ingress to Open WebUI is allowed only from the Istio ingress gateway.
- Liveness and readiness probes plus modest resource requests and limits are set, so the pod doesn't starve Ollama.
- **Optional decision point: SearXNG web search.**
  - Decision: enable it or skip it. The default is skip.
  - If enabled, SearXNG runs as a ClusterIP-only Deployment, in `open-webui` or its own namespace.
  - Open WebUI's web search is configured to use it, and Hermes may also use it as a search backend (this requires a matching egress allowance in spec 04's Istio policy).
  - The Open WebUI egress policy gains a single rule to SearXNG.
  - SearXNG's own egress to public search engines is a documented, explicit exception. It is never exposed through the ingress.
  - If skipped, no SearXNG resources exist, and the base spec is still complete.

## Acceptance Criteria

- [ ] `kubectl get ns open-webui` succeeds, and the Open WebUI pod reaches `Ready`.
- [ ] The image tag is pinned and the manifests contain no plaintext secret values.
- [ ] `WEBUI_SECRET_KEY` comes from a Kubernetes Secret created per the secrets approach in spec 07.
- [ ] A PVC is `Bound` on the ext4-backed storage class. Chat history and the user account survive a pod restart.
- [ ] From Windows, `http://open-webui.localhost` (or the chosen name) loads the Open WebUI login page through the Istio ingress gateway.
- [ ] The first-user admin signup works once, and afterwards the signup route and API are rejected.
- [ ] A chat in the UI returns a completion, via LiteLLM, from a model served by in-cluster Ollama.
- [ ] No Ingress, HTTPRoute or VirtualService targets Ollama, OpenViking, LiteLLM or Hermes, and their Services are of type `ClusterIP`.
- [ ] No `NodePort`, `LoadBalancer` or `hostPort` exists for Open WebUI, Ollama, OpenViking or Hermes.
- [ ] The service is unreachable from another LAN host, which is verified by a connection attempt to the WSL IP and Windows host IP from a second device.
- [ ] From the Open WebUI pod, a connection to LiteLLM and a DNS lookup succeed. A connection to Ollama directly, an arbitrary external IP or other in-cluster services (for example OpenViking or Hermes) is blocked.
- [ ] If SearXNG is enabled, a web search from the UI succeeds, and a direct Open WebUI connection to anything other than LiteLLM, DNS or SearXNG remains blocked.
- [ ] If SearXNG is skipped, the acceptance criteria above pass without any SearXNG resources.
- [ ] `deploy/open-webui/README.md` documents setup and teardown steps, the chosen hostname and the SearXNG decision.
