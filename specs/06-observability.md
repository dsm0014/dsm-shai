# Spec 06 — Observability

**Status:** TODO

## Purpose
Add lightweight monitoring for the k3s stack so GPU/VRAM pressure, WSL memory pressure and pod health are visible and alerting. The 16GB RTX 4080 is shared by chat, embedding and VLM models (spec 02 VRAM budget), so VRAM visibility is the top priority. Depends on spec 01 (cluster, GPU plugin), spec 02 (VRAM budget), spec 05 (ingress pattern) and spec 08 (Istio ingress gateway, mesh telemetry).

## Behavior
- Deploy everything into a dedicated k3s namespace `monitoring`, with manifests in `deploy/monitoring/`.
- **GPU metrics:** run NVIDIA DCGM exporter on the GPU node, using the GPU plugin and runtime from spec 01.
  - Document which DCGM metrics actually work on WSL2, covering at least framebuffer used/free, GPU utilization, temperature and power. Record the result in `deploy/monitoring/README.md`.
  - If DCGM lacks the needed metrics or fails to start on WSL2, fall back to a small `nvidia-smi`-based exporter (DaemonSet or sidecar). It must expose VRAM used/total, utilization, temperature and per-process VRAM where available.
  - Use stable metric names via recording rules or relabeling, so dashboards and alerts work with either source.
- **Metrics store:** run Prometheus, or a single-binary equivalent such as VictoriaMetrics.
  - Set modest CPU and memory requests and limits.
  - Bound retention by both time (e.g. 15d) and size.
  - Store data on a PVC on the WSL ext4 volume, not a `/mnt/c` path.
  - Expose it as ClusterIP only, with no Ingress or hostPort.
- **Scrape targets:** DCGM or nvidia-smi exporter, node-exporter (WSL memory against the 24GB cap from spec 01), kube-state-metrics, cAdvisor/kubelet for pod CPU and memory, Istio mesh metrics (spec 08), LiteLLM per-key and per-model metrics (spec 09), and Ollama loaded-model data.
  - If Ollama has no native `/metrics`, use a lightweight exporter polling `/api/ps` for loaded models and VRAM, plus request activity from LiteLLM metrics (spec 09). Document what is covered.
- **Grafana:** provision the datasource and dashboards from ConfigMaps (no manual setup), with persistent storage and a non-default admin credential kept in a Secret managed per spec 07.
  - GPU dashboard: VRAM used against the 16GB total, utilization and temperature.
  - Ollama dashboard: request activity and loaded models.
  - Workloads dashboard: pod CPU and memory for ollama, openviking, hermes and open-webui.
  - Node dashboard: memory against the 24GB WSL cap, and OOM kills.
- **Exposure:** expose Grafana through the Istio ingress gateway (spec 08) using the spec 05 pattern, bound to host-local access only (not LAN-reachable).
- **Alert rules** (Prometheus or vmalert rules, visible in Grafana):
  - VRAM used above ~15GiB for 5m.
  - GPU temperature above a documented threshold (e.g. 83C).
  - WSL memory pressure (available memory below ~10% of the 24GB cap) and any OOM kill.
  - PVC usage above 85%, covering the monitoring PVC itself.
  - Pod crash loops (restarts or CrashLoopBackOff) in the stack namespaces.
- Alerts need no external notifier initially. Viewing them in Grafana or Prometheus is enough, and a webhook receiver can be added later.
- Total monitoring footprint must stay small enough not to materially reduce the memory and VRAM headroom budgeted in specs 01 and 02. The monitoring stack must not use GPU memory itself beyond the exporter's negligible overhead.

## Acceptance Criteria
- [ ] The `monitoring` namespace exists and all its pods are Running and Ready after a clean apply.
- [ ] A documented check lists which GPU metrics are available on this WSL2 setup, and states whether DCGM or the nvidia-smi fallback is in use.
- [ ] VRAM used, GPU utilization and temperature are queryable in Prometheus and match `nvidia-smi` within a small tolerance.
- [ ] Loading a model in Ollama visibly raises VRAM in the GPU dashboard, and the loaded model appears in the Ollama dashboard.
- [ ] The metrics store has resource limits, bounded time and size retention, and a PVC on the ext4 volume. Data survives a pod restart.
- [ ] Prometheus has no external exposure, and a request to it from a non-host LAN machine fails.
- [ ] Grafana loads at its host-local ingress URL with datasource and dashboards provisioned, with no manual import. It is unreachable from other LAN hosts.
- [ ] Dashboards show pod CPU and memory for ollama, openviking, hermes and open-webui, and node memory against the 24GB cap.
- [ ] Each alert rule loads without error and appears in the alerts UI. Fire tests pass for at least VRAM above threshold (e.g. temporarily lowered), a crash-looping test pod, and PVC fill.
- [ ] Steady-state monitoring stack memory is measured and recorded, and stays within the documented limits.
- [ ] No secrets are committed in plaintext, and Grafana does not use the default admin password.
- [ ] `deploy/monitoring/README.md` documents the GPU metric availability check, deploy steps, dashboards and alert thresholds.
