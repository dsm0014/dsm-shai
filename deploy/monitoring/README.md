# deploy/monitoring

Monitoring (spec 06), namespace `monitoring`. Status: **running and verified** (GPU, Ollama, alerts, fire tests, Grafana through the host-local ingress). Two items need the branch merged to `main` before Flux owns them (see the end).

## Chart and pins

- `kube-prometheus-stack` **93.3.0** (HelmRelease `deploy/monitoring/helmrelease.yaml`), Grafana 13.3.1, Prometheus Operator, kube-state-metrics, node-exporter.
- **Disabled:** Alertmanager (spec 06: alerts are viewed in Prometheus and Grafana). Control-plane scrapes for etcd, controller-manager, scheduler and kube-proxy (k3s embeds them and does not expose them). Verified: no Alertmanager pod, and no control-plane scrape pools in `/api/v1/targets`.
- **Cross-namespace selection:** ServiceMonitors, PodMonitors and rules are picked up from every namespace.
- **Prometheus:** retention **15d**, size limit **20GiB**, PVC 30Gi on `local-path` (WSL ext4). The size limit is below the PVC, so retention trims before the volume fills. Verified with `/api/v1/status/flags`. The spec's example was 8GB; 20GiB is kept because the PVC already exists at 30Gi.
- **Operator pod** is outside the Istio mesh (`istio.io/dataplane-mode: none`). The kube-apiserver calls its admission webhook, which is not mesh traffic (see `deploy/istio/README.md`).

## GPU metrics on WSL2 (check result)

DCGM is not used: the image has no `dcgmi`, and the spec's fallback is an `nvidia-smi` exporter. Checked on this host:

| Metric | Available | Exporter name |
|---|---|---|
| Memory used / total (MiB) | yes | `gpu_memory_used_mib`, `gpu_memory_total_mib` |
| Utilization (%) | yes | `gpu_utilization_percent` |
| Temperature (C) | yes | `gpu_temperature_celsius` |
| Power (W) | yes | `gpu_power_watts` |
| Per-process VRAM | **no** (`--query-compute-apps` returns nothing on WSL2) | not exported |

Agreement with the host `nvidia-smi`: memory 11012 MiB in both; temperature 40 C in both; power 5.79 W and 5.77 W.

## Exporter (`gpu-exporter/`)

One Python exporter (`exporter.py`, stdlib only) in the pinned LiteLLM image, which already has `python3`. It runs on the `nvidia` runtime with `NVIDIA_DRIVER_CAPABILITIES=utility` so `nvidia-smi` is injected. It also polls Ollama `/api/ps` for loaded models, VRAM and context length (`ollama_model_vram_bytes`, `ollama_loaded_models`). Port 9400, ServiceMonitor every 30s. The exporter's identity is allowed on Ollama by the mesh policy.

Covered: GPU memory, utilization, temperature, power, and the loaded-model VRAM per model. Not covered: per-process VRAM, and request activity per model (taken from LiteLLM metrics instead).

## Dashboards (`extras/dashboards/`, provisioned from ConfigMaps)

- **GPU and Ollama:** VRAM used against total, utilization, temperature, power, loaded-model VRAM, LiteLLM requests per model.
- **Workloads and node:** pod memory and CPU for `ollama`, `openviking`, `hermes`, `open-webui`; node memory against the 24 GiB WSL cap; OOM kills; memory available %.

Loaded by the Grafana dashboard sidecar (label `grafana_dashboard: "1"`), with no manual import. Verified: the sidecar wrote both files and Grafana reloaded (200).

## Alert rules (`extras/alerts.yaml`)

| Alert | Expression | For |
|---|---|---|
| `GpuVramAbove15GiB` | VRAM used > 15360 MiB | 5m |
| `GpuTemperatureHigh` | GPU temperature > 83 C | 5m |
| `OllamaExporterDown` | `ollama_up == 0` or absent | 5m |
| `WslMemoryPressure` | available memory < 10% of the WSL VM | 10m |
| `NodeOomKill` | `increase(node_vmstat_oom_kill[10m]) > 0` | none |
| `PvcUsageAbove85Percent` | used / capacity > 0.85 | 10m |
| `PodCrashLooping` | restarts > 3 in 15m (stack namespaces) | none |

## Fire tests (run 2026-11-16)

| Test | Method | Result |
|---|---|---|
| VRAM above threshold | temporary rule `max(gpu_memory_used_mib) > 100` | **firing**, value 11012 MiB |
| Crash-looping pod | pod exiting 1 in `monitoring` (4 restarts) | `PodCrashLooping` **firing** |
| PVC fill | temporary rule with threshold 0.0001 on the Prometheus PVC | **firing** |

Notes on the PVC test: `local-path` reports the host filesystem's capacity (about 950 GB), so filling 85% of a PVC is not practical on this host. The test lowers the threshold to prove the rule fires. The real threshold is unchanged. All three temporary rules were removed.

## Persistence

Prometheus restarted: a 30-minute window of samples still returns (60 samples, the oldest 1802 s old). Grafana data is on its PVC.

## Footprint (measured with `kubectl top`, 2026-11-16)

| Pod | CPU | Memory |
|---|---|---|
| Prometheus | 13m | 522Mi (limit 2Gi, request 512Mi) |
| Grafana | 12m | 528Mi |
| kube-state-metrics | 1m | 46Mi |
| Prometheus operator | 2m | 30Mi |
| node-exporter | 1m | 16Mi |
| gpu-exporter | 2m | 12Mi |
| **Total** | **about 31m** | **about 1.15 GiB** |

No GPU memory is used by the stack. The exporter only runs `nvidia-smi`.

## Exposure

- Prometheus: ClusterIP only. No Ingress, no hostPort.
- Grafana: `grafana.localhost` through the Istio ingress gateway (`extras/grafana-route.yaml`), with a policy allowing only the ingress gateway's identity on port 3000. Verified: the login page returns 200 through the gateway.
- **Not verified:** unreachable from another LAN host (needs a second device); a Windows browser test; the Grafana admin password is from the `grafana-admin` SOPS Secret (not the default).

## Deploy and teardown

```sh
kubectl apply -k deploy/monitoring/extras        # dashboards, alerts, Grafana route
kubectl apply -k deploy/monitoring/gpu-exporter  # exporter
kubectl -n istio-system port-forward svc/istio-ingressgateway 8080:80   # then open http://grafana.localhost:8080
```

## Applied through Flux

The HelmRelease changes (`prometheusOperator.podLabels`, `retention: 15d`) and the stages `gpu-exporter`, `monitoring-extras` and `mesh-policies` are on `main` and Flux owns them. All Flux stages report Ready.
