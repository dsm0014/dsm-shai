# Spec 05 — Web UI Ingress

**Status:** TODO

## Purpose

Deploy Open WebUI as the human-facing chat front end in its own `open-webui` namespace, backed by the in-cluster Ollama endpoint (spec 02). Expose it to the local machine only, through k3s's bundled Traefik (spec 01), with authentication enabled and data persisted.

## Behavior

- Open WebUI runs in namespace `open-webui` as a single-replica Deployment (or StatefulSet) pinned to a specific image tag, never `latest`. Manifests live in `deploy/open-webui/`.
- `OLLAMA_BASE_URL` points at Ollama's in-cluster ClusterIP service DNS name from spec 02, and no external model or API endpoints are configured.
- Open WebUI's data directory is mounted from a PVC on the k3s `local-path` storage class. This storage must live on the WSL ext4 volume, not under `/mnt/c`.
- Authentication is enabled (`WEBUI_AUTH=True`). The first account created becomes admin, and then signup is disabled (`ENABLE_SIGNUP=False`) and stays disabled.
- `WEBUI_SECRET_KEY` is delivered through a Kubernetes Secret, managed per the secrets approach in spec 07. No secret value appears in manifests, ConfigMaps, logs or git history.
- Open WebUI gets a ClusterIP Service and a Traefik `Ingress` (or `IngressRoute`). Traefik's own listener must be reachable from Windows via `localhost` / WSL2 port forwarding.
- The ingress host rule is `open-webui.localhost`, or a hosts-file name if the user prefers. A plain `localhost` path works as a fallback.
- Exposure is host-local only. Traefik is not bound to a LAN or public interface, and no `LoadBalancer`, `NodePort` or `hostPort` is created for any workload in this spec.
- Rule: Ollama, OpenViking and Hermes stay `ClusterIP`-only and must never be referenced by any Ingress or IngressRoute. Open WebUI is the only workload exposed through Traefik.
- A NetworkPolicy in `open-webui` sets default-deny egress. Egress is allowed only to the Ollama pods (its namespace and port), to cluster DNS (kube-dns, UDP/TCP 53), and to SearXNG if enabled.
- Ingress to Open WebUI is allowed only from the Traefik pods in `kube-system`.
- Liveness and readiness probes plus modest resource requests and limits are set, so the pod doesn't starve Ollama.
- **Optional decision point: SearXNG web search.**
  - Decision: enable it or skip it. The default is skip.
  - If enabled, SearXNG runs as a ClusterIP-only Deployment, in `open-webui` or its own namespace.
  - Open WebUI's web search is configured to use it, and Hermes may also use it as a search backend (this requires a matching egress rule in spec 04's NetworkPolicy).
  - The Open WebUI NetworkPolicy gains a single egress rule to SearXNG.
  - SearXNG's own egress to public search engines is a documented, explicit exception. It is never exposed through the ingress.
  - If skipped, no SearXNG resources exist, and the base spec is still complete.

## Acceptance Criteria

- [ ] `kubectl get ns open-webui` succeeds, and the Open WebUI pod reaches `Ready`.
- [ ] The image tag is pinned and the manifests contain no plaintext secret values.
- [ ] `WEBUI_SECRET_KEY` comes from a Kubernetes Secret created per the secrets approach in spec 07.
- [ ] A PVC is `Bound` on the ext4-backed storage class. Chat history and the user account survive a pod restart.
- [ ] From Windows, `http://open-webui.localhost` (or the chosen name) loads the Open WebUI login page through Traefik.
- [ ] The first-user admin signup works once, and afterwards the signup route and API are rejected.
- [ ] A chat in the UI returns a completion from a model served by in-cluster Ollama.
- [ ] No Ingress or IngressRoute targets Ollama, OpenViking or Hermes, and their Services are of type `ClusterIP`.
- [ ] No `NodePort`, `LoadBalancer` or `hostPort` exists for Open WebUI, Ollama, OpenViking or Hermes.
- [ ] The service is unreachable from another LAN host, which is verified by a connection attempt to the WSL IP and Windows host IP from a second device.
- [ ] From the Open WebUI pod, a connection to Ollama and a DNS lookup succeed. A connection to an arbitrary external IP or other in-cluster services (for example OpenViking or Hermes) is blocked.
- [ ] If SearXNG is enabled, a web search from the UI succeeds, and a direct Open WebUI connection to anything other than Ollama, DNS or SearXNG remains blocked.
- [ ] If SearXNG is skipped, the acceptance criteria above pass without any SearXNG resources.
- [ ] `deploy/open-webui/README.md` documents setup and teardown steps, the chosen hostname and the SearXNG decision.
