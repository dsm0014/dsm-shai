# deploy/istio

Istio service mesh (spec 08), ambient mode on k3s. Pinned to Istio **1.30.8** (all charts together). Flux installs the charts in order (`helmreleases.yaml`: base, cni, istiod, ztunnel, ingress gateway). Part B (policy, STRICT mTLS, egress) lives in `policies/` and the `mesh-policies` Flux stage.

## Mode decision

Ambient, with no sidecars. Sidecars cost roughly 50 to 100 MB per pod, which does not fit the 24 GB WSL cap alongside a 14B-class model. Waypoints are used only where L7 policy is needed. None is deployed yet.

## WSL2 verification (ambient works on this host)

- k3s CNI paths set through `istio-cni` (k3s profile). `istio-cni-node`, `ztunnel` and `istiod` are Running.
- Traffic capture: after enrolment, the ztunnel access log shows `src.workload` and `dst` for Prometheus, kube-state-metrics and the LLM traffic. This is the evidence that the pods' traffic is intercepted.
- Application checks passed after enrolment: Hermes to LiteLLM, LiteLLM to Ollama, Open WebUI through the ingress, OpenViking memory search, Prometheus scraping.

### Restart recovery (after `wsl --shutdown`, 2026-11-16)

- ztunnel does not re-enrol pods that were already running when it restarted. Their access log shows `connection refused` (HBONE, port 15008) or `connection reset by peer` from the clients, and the pod never logs `pod received, starting proxy`.
- Fix: delete the affected pods (the Deployment or StatefulSet recreates them, PVCs are kept). Pods that came up after ztunnel are fine. Check with `kubectl -n istio-system logs <ztunnel> | grep "pod received"`.
- Affected here: `openviking`, `litellm`, `litellm/postgres-0`, `monitoring/prometheus-...-0` (seen again after the PR #9 rollout; Kiali could not reach Prometheus until its pod was recreated). Hermes then needs its own restart so its MCP client reconnects; a `rollout restart` is reverted by Flux on the next reconcile, so delete the pod instead.

## Memory budget (measured, `kubectl top`)

| Component | Measured | Budget |
|---|---|---|
| istiod | 106 Mi | 512 Mi |
| ztunnel (one node) | 11 Mi | 256 Mi |
| istio ingress gateway | 66 Mi | 256 Mi |
| istio-cni node | 63 Mi | n/a (no budget set) |
| **Total** | **about 250 Mi** | **about 1.5 GB** |

Ollama (chat model at 64K) used about 7.6 GiB of container memory at the time of measurement, within its 12 Gi limit.

## Rollout (as performed, 2026-11-16)

1. Enrol `ollama`, `litellm`, `openviking`, `hermes`, `open-webui`, `monitoring` with `istio.io/dataplane-mode=ambient`. Verified permissive flows still work (namespace labels are now in `deploy/platform/namespaces.yaml`).
2. Identity-based `AuthorizationPolicy` per workload, with a deny-all baseline per namespace (`policies/policies.yaml`). Principals are ServiceAccounts: LiteLLM to Ollama (plus the embed-pin CronJob), Open WebUI / OpenViking / Hermes / Prometheus to LiteLLM, LiteLLM to Postgres, Hermes to OpenViking, the ingress gateway to Open WebUI, Prometheus to the monitoring namespace.
3. Mesh-wide `PeerAuthentication` `STRICT` (`policies/mtls.yaml`).
4. Rollback drill: switched to `PERMISSIVE`, confirmed the flows, restored `STRICT`.

### Verification results

| Check | Result |
|---|---|
| Allowed: Hermes to LiteLLM | PONG |
| Allowed: LiteLLM to Ollama | chat completion |
| Allowed: Open WebUI to LiteLLM, and the ingress login | 200 |
| Allowed: Hermes to OpenViking; OpenViking memory search under STRICT | found |
| Allowed: Prometheus scrapes LiteLLM and the monitoring targets | `up=1`; 12 targets up, 0 down |
| Denied: Open WebUI to Ollama directly | connection reset |
| Denied: Hermes to Ollama directly | connection reset |
| Denied: Hermes to Postgres | connection reset |
| Denied: plaintext from a non-mesh pod (`default` namespace) to LiteLLM, Ollama and OpenViking | connection reset |
| Rollback: PERMISSIVE, then STRICT | flows restored |

## Documented exceptions

- **Prometheus operator pod** (`istio.io/dataplane-mode: none`, set in the Helm values `prometheusOperator.podLabels`). The kube-apiserver calls its admission webhook from outside the mesh, so under STRICT those calls would be refused.
- **node-exporter** is host-networked, so it is not a mesh workload.
- **kubelet health probes** are allowed by ztunnel; the workloads stay Ready under STRICT.

## Egress: gap and current control

- `outboundTrafficPolicy: REGISTRY_ONLY` is **not applied**. In ambient mode, ztunnel does not enforce it for destinations that are not registered, so it would not block traffic to arbitrary hosts. Measured before the fix: Hermes reached `pypi.org`, `github.com` and `example.com`.
- The current control is a Kubernetes NetworkPolicy, `deploy/hermes/egress-networkpolicy.yaml`. It allows only DNS, LiteLLM (4000), OpenViking (1933) and the HBONE tunnel (15008). Verified: public hosts are refused, LiteLLM and OpenViking still work, and Hermes still answers.
- **Not met in general:** the spec's hostname allowlist. NetworkPolicy works at IP level, so hostnames cannot be listed. **It is implemented for the hermes pod (specs 11, 12 and 15)** through a Squid proxy (`deploy/istio/egress/`), restricted to the hermes service account: a restricted listener (GitHub, Anthropic, Discord) and an open-web listener for Haiku research. All other egress stays default-deny. Why a proxy and not a waypoint, and when to revisit: `deploy/istio/egress/README.md`, "Alternatives considered".

## Not done

- **Kiali:** off by default (not in Git). "Works when enabled" checked 2026-11-16: `kiali-server` 2.34.1 in a throwaway namespace enrolled in ambient, anonymous auth, Prometheus at `kube-prometheus-stack-prometheus.monitoring.svc:9090`. Its graph showed 6 workloads and 5 edges across `litellm`, `hermes`, `openviking` and `ollama`. Enabling it needs an `ALLOW` policy for `cluster.local/ns/<kiali-ns>/sa/kiali` to the Prometheus pod on port 9090 (the deny-all baseline resets it otherwise). The test install, namespace and policy were removed afterwards.
- **Mesh metrics in Grafana:** ztunnel and istiod metrics are not yet in a Prometheus ServiceMonitor or a dashboard (spec 06 part B, step 12).
- **Grafana behind the gateway:** Grafana is routed at `grafana.localhost` through the ingress gateway. `kubectl port-forward` to mesh workloads is now refused by the deny-all policy, so use `kubectl exec` or a debug container for in-mesh checks.

## Incident: enrolment lost to Flux (2026-11-16)

- **What happened:** the `platform` Flux stage reconciles `deploy/platform/namespaces.yaml` from `main`. On `main`, the namespaces carried no ambient label, so Flux removed the labels I had added by hand (`ollama`, `hermes`, `openviking`, `monitoring`). Pods created after that were not redirected into ambient. Under STRICT, Hermes and OpenViking calls to LiteLLM were refused (`istio_converted_static_strict`), because their traffic went out without mTLS. `ollama` and `monitoring` were no longer enforced.
- **Why it was not seen at once:** the backup restarted Hermes and OpenViking, and their new pods were the first created after the label was lost.
- **Fix:** the labels now live in `deploy/platform/namespaces.yaml` on `main`, and the `platform` Flux stage is no longer suspended; it reconciles normally. The labels were re-applied and the workloads restarted. Verified after the fix: the redirection annotation is `enabled` on all pods in the four namespaces; OpenViking and Hermes reach LiteLLM; LiteLLM reaches Ollama; Open WebUI and Hermes are refused on Ollama directly; a plaintext request from a non-mesh pod is refused; 19 Prometheus targets are up.
- **Rule from this:** a namespace label that the mesh needs must be in the manifest that Flux owns, and a new pod must show the redirection annotation before a policy is trusted.

## Rollback

```sh
# mTLS back to permissive (keeps policies)
kubectl -n istio-system patch peerauthentication default --type merge -p '{"spec":{"mtls":{"mode":"PERMISSIVE"}}}'
# remove a namespace from the mesh
kubectl label namespace <ns> istio.io/dataplane-mode-
# remove the policies
kubectl delete -k deploy/istio/policies
kubectl delete -f deploy/hermes/egress-networkpolicy.yaml
```

Note: `kubectl port-forward` is refused for enrolled workloads under the deny-all policy. Use `kubectl exec` for in-cluster checks.
