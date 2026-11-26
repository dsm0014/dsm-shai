# Spec 08 — Istio Service Mesh

**Status:** PARTIAL (ambient enrolment, identity policies, STRICT mTLS and rollback verified; hostname egress through the Squid proxy; see deploy/istio/README.md)

> **Egress, current state:** hostname egress control is a Squid forward proxy (`deploy/istio/egress/`), because `REGISTRY_ONLY` is not enforced by ambient ztunnel. Only the hermes pod may call it (AuthorizationPolicy `squid-from-hermes`, principal `cluster.local/ns/hermes/sa/hermes`, ports 3128 and 3129). Port 3128 allows GitHub, `api.anthropic.com` and Discord; port 3129 allows any public host for Haiku research (spec 15). Private, loopback and link-local destinations are denied on both. All other namespaces stay default-deny.

## Purpose
Adopt Istio (ambient mode) as the security, routing and egress-control layer of the single-node k3s stack, giving identity-based mTLS and authorization, a single ingress, and hostname-level egress control. It must fit within the ~24GB WSL2 RAM cap shared with a 14B model on one GPU.

## Behavior
- **Depends on:** spec 01 (k3s must start with `--disable=traefik`; Traefik is removed), specs 02-07 as mesh members, and spec 09 (the `litellm` namespace is a mesh member and the only caller of Ollama).
- **Mode decision (settled):** use ambient mode (ztunnel DaemonSet, no sidecars). Sidecar mode (~50-100MB Envoy per pod) is rejected for the 24GB cap. Deploy waypoint proxies only where L7 policy is needed (Hermes egress, HTTP-path rules), not per namespace by default.
- **CNI:** ambient needs `istio-cni` with k3s's non-default paths (`cniBinDir=/var/lib/rancher/k3s/data/current/bin`, `cniConfDir=/var/lib/rancher/k3s/agent/etc/cni/net.d`). Verify on WSL2 (kernel/iptables support, ztunnel traffic redirection) before relying on it. Record the result in `deploy/istio/README.md`.
- **Install:** use Helm or `istioctl` with a pinned Istio version. Keep values/IstioOperator files in `deploy/istio/`: base, istiod, istio-cni, ztunnel, and gateway. Include an install script and an uninstall script.
- **Memory budget (in values, requests and limits):** istiod ≤ 512MB, each ztunnel ≤ 256MB (single node, so one), ingress gateway ≤ 256MB, each waypoint ≤ 256MB. The total mesh control and data plane stays ≤ ~1.5GB. Document the budget against the 24GB cap and the Ollama model footprint.
- **Membership:** label the `ollama`, `openviking`, `hermes`, `open-webui`, `litellm` and `monitoring` namespaces `istio.io/dataplane-mode=ambient`. Enrol namespaces one at a time.
- **mTLS:** mesh-wide `PeerAuthentication` set to `STRICT`. Plaintext in-mesh traffic is rejected. Document any exceptions, such as Prometheus scrape targets, explicitly.
- **Authorization:** each namespace gets a default-deny `AuthorizationPolicy` plus explicit per-service ALLOW rules keyed on ServiceAccount identity (for example, only litellm may call ollama). Remove the identity-based rules made redundant from specs 03/04/05 NetworkPolicies. Keep a baseline default-deny NetworkPolicy as defense-in-depth only where it is cheap, and do not duplicate L7 rules there.
- **Ingress:** an Istio ingress gateway (`Gateway` + `HTTPRoute`/`VirtualService`) replaces Traefik as the single host-local entry point for Open WebUI and Grafana. Bind only to localhost / the host-local port. Nothing else is exposed.
- **Egress:** the hermes pod reaches the internet only through the Squid proxy in `egress-proxy` (see the egress note above). The allowlist is `deploy/istio/egress/squid.conf`, a NetworkPolicy removes every direct route, and an AuthorizationPolicy limits callers to the hermes service account. This resolves spec 04's question on hostname-based egress. The ServiceEntry-plus-waypoint design was evaluated and not adopted; the revisit triggers are in `deploy/istio/egress/README.md`.
- **Ollama and streaming:** the Ollama route must set a long or disabled request timeout (≥ 10 minutes) and no idle timeout for streamed tokens. It must also set `retries.attempts: 0` so generations are never duplicated, and keep response buffering off (no buffering filters; SSE/chunked responses flush incrementally). Apply the same settings on the gateway route for Open WebUI streaming. Do not use L7 waypoint retries or buffering on the path unless these settings are verified.
- **Telemetry:** Istio and ztunnel metrics (`istio_tcp_*`, plus waypoint `istio_requests_total`) are scraped by the spec 06 Prometheus. Ship a ServiceMonitor/PodMonitor and a Grafana mesh dashboard. Mind metric cardinality and retention on the single node.
- **Kiali:** optional and off by default (`kiali.enabled=false`). When enabled it must fit the memory budget and sit behind the ingress gateway.
- **Rollout order:** (1) k3s with Traefik disabled; (2) istio-base, istio-cni, istiod, ztunnel; (3) ingress gateway with Open WebUI and Grafana routes; (4) enrol namespaces with PERMISSIVE mTLS and verify; (5) add ALLOW policies, then default-deny; (6) switch mTLS to STRICT; (7) apply egress REGISTRY_ONLY with the Hermes allowlist. Verify after each step.
- **Delivery:** with Flux (spec 10) this order is encoded as `dependsOn` chains (HelmRelease chain for base, cni, istiod, ztunnel, gateway, then policies last), and the PERMISSIVE-to-STRICT and egress steps are commits (or resumed Kustomizations). The shell steps remain documented as the manual and break-glass path. `flux-system` stays out of the mesh.
- **Rollback:** every step is reversible. Remove the namespace label to leave the mesh, delete the policies, and set mTLS back to PERMISSIVE and egress to ALLOW_ANY. A full uninstall script restores prior NetworkPolicies. Keep the NetworkPolicy manifests from specs 03/04/05 available until the mesh policies are verified.

## Acceptance Criteria
- [ ] k3s runs with Traefik disabled; the Istio ingress gateway is the only entry point and serves Open WebUI and Grafana on localhost.
- [ ] Istio version is pinned; the `deploy/istio/` values install cleanly with one script and uninstall cleanly with another.
- [ ] Ambient mode works on WSL2 with k3s CNI paths (istio-cni and ztunnel healthy, traffic captured), with the verification result recorded.
- [ ] Measured memory of istiod + ztunnel + gateway (+ waypoints) stays within the documented budget, and Ollama with the 14B model loads without OOM.
- [ ] A plaintext request from a non-mesh pod to a mesh workload is rejected.
- [ ] An unauthorized caller (for example, open-webui calling ollama directly) receives 403 / RBAC denied; an authorized caller (litellm) succeeds.
- [x] The hermes pod reaches the internet only through the Squid proxy on port 3128: from the hermes pod, a request to an allowlisted hostname (the GitHub hosts, plus `api.anthropic.com` and the Discord hosts added by specs 12 and 15) succeeds and a request to any other hostname fails (verified 2026-11-17). Istio `REGISTRY_ONLY` does not block unregistered hosts in ambient mode, so the allowlist must be enforced by the proxy, not by `REGISTRY_ONLY`.
- [ ] A streaming chat completion through the mesh (Open WebUI -> LiteLLM -> Ollama) delivers tokens incrementally, without buffering, timeout, or duplicate generation on a long response.
- [x] Mesh metrics appear in Prometheus and in a Grafana dashboard; Kiali is off by default and works when enabled. Verified 2026-11-26 for the metrics and the dashboard (`deploy/monitoring/README.md`, Dashboards); Kiali was checked 2026-11-16 (`deploy/istio/README.md`).
- [ ] Hand-written NetworkPolicy rules replaced by identity-based policies are removed from specs 03/04/05; specs 05 and 06 no longer reference Traefik.
- [ ] The rollback procedure was exercised (mTLS back to PERMISSIVE, namespace un-enrolled) and services keep working.
- [ ] `deploy/istio/README.md` documents the mode decision, install, rollout order, rollback and the WSL2 verification result.
