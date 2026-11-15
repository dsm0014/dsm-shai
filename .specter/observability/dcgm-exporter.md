# NVIDIA DCGM Exporter for GPU Metrics

**Tags:** dcgm, gpu, prometheus, helm, vram, wsl2, spec-06

Source: github.com/NVIDIA/dcgm-exporter (README, `etc/`, `deployment/`, tests READMEs; chart default image tag 4.9.0 at time of ingest).

## What it is

A DaemonSet-deployable exporter that serves NVIDIA DCGM GPU telemetry in Prometheus format on `:9400` (`/metrics`, `/health`). Config is a v2 YAML (`config.yaml`) plus a counters CSV (`default-counters.csv`, rows of `DCGM_FIELD, prometheus_type, help`). Collection interval defaults to 30s.

## VRAM and utilisation metrics

Metric names use a `_BYTES` or `_RATIO` form in current releases (older docs show `DCGM_FI_DEV_FB_USED`):
- `DCGM_FI_DEV_FB_USED_BYTES`, `DCGM_FI_DEV_FB_FREE_BYTES`, `DCGM_FI_DEV_FB_CAPACITY_BYTES`, `DCGM_FI_DEV_FB_RESERVED_BYTES`
- `DCGM_FI_DEV_GPU_UTIL_RATIO`, `DCGM_FI_DEV_MEMORY_UTIL_RATIO`, `DCGM_FI_DEV_GPU_TEMP_CELSIUS`, `DCGM_FI_DEV_BOARD_POWER_WATTS`, `DCGM_FI_DEV_SM_CLOCK_HERTZ`, `DCGM_FI_DEV_XID_ERROR`, `DCGM_FI_DEV_GPU_ENERGY_JOULES_TOTAL`
- `DCGM_FI_PROF_*` profiling fields are annotated "supported on Nvidia datacenter Volta GPUs and newer", so do not expect them on a GeForce RTX 4080.

A custom metric list **replaces** the default list (it is not additive). Mounting a volume over `/etc/dcgm-exporter` hides `config.yaml` and makes the exporter fail at startup.

## Kubernetes (Helm chart)

- `helm install dcgm-exporter dist/dcgm-exporter.tgz` (build with `task helm:package`; the in-tree chart needs git symlink support, so packaged charts are safer on Windows checkouts).
- The chart creates a `ServiceMonitor`, so install the Prometheus Operator CRDs first or set `serviceMonitor.enabled=false`.
- If the NVIDIA driver libraries are not injected, set `runtimeClassName: nvidia`. Tolerate the `nvidia.com/gpu` taint if present.
- Defaults to note: runs as root with `SYS_ADMIN` (needed for profiling metrics), `priorityClassName: system-node-critical`, requests 100m CPU / 128Mi, limits 200m / 512Mi, `networkPolicy.enabled=false`.
- Keep `server.write_timeout` (30s) above `serviceMonitor.scrapeTimeout` (25s), which must be at most `interval` (30s).
- Config changes need a pod restart. With `configMap.existingName`, restart manually. Upgrading from 4.8 to 4.9 moves several values into `config`. Do not use `--reuse-values`.
- Under Istio ambient, the exporter has to be enrolled, or scraped from a labelled namespace with an explicit AuthorizationPolicy or a documented mTLS exception.

## WSL2 and consumer GPU caveat

Nothing in the repo documents WSL2 or GeForce support, and the stated requirement is "NVIDIA GPU-compatible hardware for use with DCGM". DCGM targets datacenter GPUs on a native Linux driver. On WSL2 with an RTX 4080 it may not initialise, or many fields may be unsupported. This matches the spec 06 fallback plan:
1. Try dcgm-exporter and check `/metrics` for `DCGM_FI_DEV_FB_USED_BYTES` first.
2. If it fails, use an `nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv` based exporter (for example a textfile collector or a small sidecar).
3. Also check Ollama's own VRAM view with `ollama ps`.

## Other

Checked-in Grafana dashboard: `grafana/dcgm-exporter-dashboard.json` in the repo. Container run example: `docker run --rm --gpus all --cap-add SYS_ADMIN nvcr.io/nvidia/k8s/dcgm-exporter:<tag>`. Exporter and DCGM versions are paired per release. Mismatches are unsupported.
