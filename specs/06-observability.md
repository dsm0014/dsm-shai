# Spec 06 — Observability

**Status:** TODO

## Purpose
Add lightweight monitoring for the k3s stack so GPU/VRAM pressure, WSL memory pressure and pod health are visible and alerting. The 16GB RTX 4080 is shared by chat, embedding and VLM models (spec 02 VRAM budget), so VRAM visibility is the top priority.

The base is the `kube-prometheus-stack` Helm chart (Prometheus Operator, Prometheus, Grafana, kube-state-metrics, node-exporter), delivered by Flux (spec 10). The GPU, Ollama and LiteLLM sources are added on top of it. Depends on spec 01 (cluster, GPU plugin, storage class), spec 02 (VRAM budget), spec 05 (ingress pattern), spec 07 (Grafana secret), spec 08 (Istio ingress gateway, mesh telemetry) and spec 10 (Flux delivery and CRD ordering).

## Behavior
- Deploy everything into a dedicated k3s namespace `monitoring`, with Helm values and manifests in `deploy/monitoring/`.
- **Delivery (Flux, spec 10):** a `HelmRepository` for the prometheus-community charts and a `HelmRelease` for `kube-prometheus-stack`. The chart version is pinned (no floating version). The HelmRelease sets `install.crds: Create` and `upgrade.crds: CreateReplace` so the Prometheus Operator CRDs (`ServiceMonitor`, `PodMonitor`, `PrometheusRule`) are present for the other specs. Install and upgrade remediation is bounded, so a bad chart bump rolls back.
- **Base stack: kube-prometheus-stack.** The HelmRelease provides the Prometheus Operator, one Prometheus instance, Grafana, kube-state-metrics and node-exporter. Basic settings:
  - **Alertmanager is disabled.** Prometheus still evaluates the alert rules below and shows them in its UI and in Grafana, which matches "no external notifier initially".
  - **Control-plane scrapes are disabled.** k3s embeds etcd, controller-manager, scheduler and kube-proxy, so the chart's default scrape jobs for them do not match. Disable those jobs and record that in the README.
  - **Cross-namespace selection.** Prometheus picks up ServiceMonitors and PodMonitors from all namespaces (`serviceMonitorSelectorNilUsesHelmValues: false`, `podMonitorSelectorNilUsesHelmValues: false`), so the DCGM, LiteLLM and Istio monitors below need no special labels.
  - **Grafana** takes its admin credential from an existing Secret (spec 07), has a PVC for its data, and runs the dashboard and datasource sidecars. The sidecars load ConfigMaps labelled `grafana_dashboard: "1"` and `grafana_datasource: "1"`. The chart's default Prometheus datasource stays on.
  - **node-exporter** runs with host networking and host PID. On WSL2, check that it reports the WSL VM's memory and not only the Windows host's.
  - **Footprint:** the chart's total requests and limits are recorded in the README and must fit the monitoring budget below.
- **GPU metrics:** run NVIDIA DCGM exporter on the GPU node, using the GPU plugin and runtime from spec 01. Its ServiceMonitor is created by the chart (`serviceMonitor.enabled`), so the exporter applies only after the kube-prometheus-stack HelmRelease is Ready.
  - Document which DCGM metrics actually work on WSL2, covering at least framebuffer used/free, GPU utilization, temperature and power. Record the result in `deploy/monitoring/README.md`.
  - If DCGM lacks the needed metrics or fails to start on WSL2, fall back to a small `nvidia-smi`-based exporter (DaemonSet or sidecar). It must expose VRAM used/total, utilization, temperature and per-process VRAM where available.
  - Use stable metric names via recording rules or relabeling, so dashboards and alerts work with either source.
- **Metrics store:** the Prometheus instance from kube-prometheus-stack.
  - Set modest CPU and memory requests and limits (for example 256Mi request, 1Gi limit).
  - Bound retention by both time (`retention: 15d`) and size (`retentionSize`, for example 8GB). Keep the size limit below the PVC size, so retention trims data before the volume fills.
  - Store data on a PVC from the default k3s `local-path` storage class, which lives on the WSL ext4 volume, not a `/mnt/c` path. Size it, for example 10Gi.
  - Expose it as ClusterIP only, with no Ingress or hostPort.
- **Scrape targets:** DCGM or nvidia-smi exporter, node-exporter (WSL memory against the 24GB cap from spec 01), kube-state-metrics, cAdvisor/kubelet for pod CPU and memory, Istio mesh metrics (spec 08), LiteLLM per-key and per-model metrics (spec 09), and Ollama loaded-model data.
  - The chart covers node-exporter, kube-state-metrics and kubelet/cAdvisor. DCGM, Istio and LiteLLM each ship a ServiceMonitor or PodMonitor in their own spec's manifests.
  - If Ollama has no native `/metrics`, use a lightweight exporter polling `/api/ps` for loaded models and VRAM, plus request activity from LiteLLM metrics (spec 09). Document what is covered.
- **Grafana:** provision the datasource and dashboards from ConfigMaps (no manual setup), with persistent storage and a non-default admin credential kept in a Secret managed per spec 07.
  - GPU dashboard: VRAM used against the 16GB total, utilization and temperature.
  - Ollama dashboard: request activity and loaded models.
  - Workloads dashboard: pod CPU and memory for ollama, openviking, hermes and open-webui.
  - Node dashboard: memory against the 24GB WSL cap, and OOM kills.
  - The chart's bundled Kubernetes dashboards may stay on, and they are not part of the acceptance set.
- **Exposure:** expose Grafana through the Istio ingress gateway (spec 08) using the spec 05 pattern, bound to host-local access only (not LAN-reachable). The route is applied with the mesh gateway routes, not with the monitoring release.
- **Alert rules** (`PrometheusRule` resources in `deploy/monitoring/alerts/`, loaded by the operator and visible in Prometheus and Grafana):
  - VRAM used above ~15GiB for 5m.
  - GPU temperature above a documented threshold (e.g. 83C).
  - WSL memory pressure (available memory below ~10% of the 24GB cap) and any OOM kill.
  - PVC usage above 85%, covering the monitoring PVC itself.
  - Pod crash loops (restarts or CrashLoopBackOff) in the stack namespaces.
- Alerts need no external notifier initially. Viewing them in Grafana or Prometheus is enough, and a webhook receiver can be added later with Alertmanager re-enabled.
- **Ordering (spec 10):** the kube-prometheus-stack HelmRelease is the `monitoring` stage, after `data` (so the secrets Kustomization has decrypted the Grafana admin Secret) and before `istio`, `inference` and `gateway`. Those stages apply ServiceMonitors or PodMonitors, so they need the CRDs first. The DCGM exporter and the Grafana route follow in the `observability` stage.
- **Egress:** the prometheus-community chart host and the image registries (quay.io, registry.k8s.io, docker.io) are allow-listed with the other chart and image hosts in spec 10.
- Total monitoring footprint must stay small enough not to materially reduce the memory and VRAM headroom budgeted in specs 01 and 02. The chart is included in that budget. The monitoring stack must not use GPU memory itself beyond the exporter's negligible overhead.

## Acceptance Criteria
- [ ] The `monitoring` namespace exists and all its pods are Running and Ready after a clean apply.
- [ ] `flux get helmreleases -n monitoring` shows `kube-prometheus-stack` Ready. The `servicemonitors`, `podmonitors` and `prometheusrules` CRDs exist, and the istio, litellm and DCGM Kustomizations apply only after the monitoring stage is Ready.
- [ ] The Prometheus runtime config (`/api/v1/status/runtimeinfo` and `/api/v1/status/flags`) shows the 15d time retention and the size limit. No Alertmanager pod runs, and the control-plane scrape jobs are absent from `/api/v1/targets`.
- [ ] A documented check lists which GPU metrics are available on this WSL2 setup, and states whether DCGM or the nvidia-smi fallback is in use.
- [ ] VRAM used, GPU utilization and temperature are queryable in Prometheus and match `nvidia-smi` within a small tolerance.
- [ ] Loading a model in Ollama visibly raises VRAM in the GPU dashboard, and the loaded model appears in the Ollama dashboard.
- [ ] The metrics store has resource limits, bounded time and size retention, and a PVC on the ext4 volume. Data survives a pod restart.
- [ ] Prometheus has no external exposure, and a request to it from a non-host LAN machine fails.
- [ ] Grafana loads at its host-local ingress URL with datasource and dashboards provisioned, with no manual import. It is unreachable from other LAN hosts.
- [ ] Dashboards show pod CPU and memory for ollama, openviking, hermes and open-webui, and node memory against the 24GB cap.
- [ ] Each alert rule loads without error and appears in the alerts UI. Fire tests pass for at least VRAM above threshold (e.g. temporarily lowered), a crash-looping test pod, and PVC fill.
- [ ] Steady-state monitoring stack memory is measured and recorded for the whole kube-prometheus-stack release, and stays within the documented limits.
- [ ] No secrets are committed in plaintext, and Grafana does not use the default admin password.
- [ ] `deploy/monitoring/README.md` documents the chart version and pinned values, the disabled components and why, the GPU metric availability check, deploy steps, dashboards and alert thresholds.
