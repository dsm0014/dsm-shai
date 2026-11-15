# Spec 01 — Platform Foundation

**Status:** TODO

## Purpose
Prepare the Windows 11 + WSL2 host and a single-node k3s cluster with GPU access, persistent storage, and the repo's `deploy/` layout. This gives the Ollama, OpenViking, and Hermes workloads a place to run.

## Behavior

**Host (Windows 11 + WSL2)**
- Target hardware is an i7-13700KF, an RTX 4080 16GB, and 32GB host RAM. About 950GB is free on the WSL ext4 volume.
- `%UserProfile%\.wslconfig` sets `memory=24GB` (up from the ~15GB default), leaving about 8GB for Windows. Swap and processor settings are explicit.
- `/etc/wsl.conf` sets `[boot] systemd=true`. After `wsl --shutdown` and restart, `systemctl is-system-running` reports `running` or `degraded` with no failures in the k3s path.
- The Windows NVIDIA driver provides GPU passthrough. No Linux display driver is installed inside WSL.
- `nvidia-smi` works inside WSL and shows the RTX 4080.

**Tooling**
- `kubectl`, `helm`, `k3s`, and `nvidia-ctk` (NVIDIA Container Toolkit) are installed. Each is pinned to a documented version.
- The install steps are scripted and idempotent under `scripts/`. Re-running them on a configured host changes nothing.

**Cluster**
- k3s runs as a systemd service in single-node mode. It uses the bundled containerd. Traefik is disabled (`--disable=traefik`) because the Istio ingress gateway (spec 08) is the single entry point; servicelb stays at its default.
- The kubeconfig is readable by the non-root user, and `kubectl get nodes` shows the node `Ready`.
- `nvidia-ctk runtime configure` registers the `nvidia` runtime with k3s's containerd. A `RuntimeClass` named `nvidia` exists.
- The NVIDIA device plugin is deployed (manifest or Helm chart in `deploy/`). The node advertises `nvidia.com/gpu: 1` as allocatable.
- A smoke-test pod requesting `nvidia.com/gpu: 1` runs `nvidia-smi` and exits 0.

**Storage**
- The k3s `local-path` provisioner is the default `StorageClass`. Its data path sits on the WSL ext4 volume, not under `/mnt/c`.
- Dedicated namespaces exist for the workloads: `ollama`, `openviking`, and `hermes`. Later specs create `open-webui`, `monitoring`, `istio-system`, `litellm` and `browser`.
- A test PVC binds and keeps its data across pod restarts.

**Repo layout**
- `deploy/` has one subdirectory per concern: `platform/` (GPU plugin, runtime class, storage), `ollama/`, `openviking/`, and `hermes/`. Later specs add `istio/`, `litellm/`, `browser/`, `open-webui/` and `monitoring/`. Each workload directory has a README stub.
- Manifests are declarative and applied with `kubectl apply -k` or `helm upgrade --install`. No secrets are committed.
- A top-level `deploy/README.md` documents the bootstrap order and the teardown and rollback steps.

**Resilience**
- The cluster and GPU access come back after a WSL restart or Windows reboot, with no manual steps beyond starting WSL.

## Acceptance Criteria
- [ ] `.wslconfig` sets memory to ~24GB, and `free -h` in WSL shows ≥ 23GB total.
- [ ] `systemd` is enabled, and `systemctl status k3s` reports active (running).
- [ ] `nvidia-smi` in WSL shows the RTX 4080 with 16GB.
- [ ] `kubectl version`, `helm version`, `k3s --version`, and `nvidia-ctk --version` all succeed.
- [ ] `kubectl get nodes` shows one node `Ready`.
- [ ] k3s was started with `--disable=traefik`, and no Traefik pods or IngressRoutes exist in `kube-system`.
- [ ] `kubectl describe node` lists `nvidia.com/gpu: 1` under Allocatable.
- [ ] The GPU smoke-test pod completes and its logs show the RTX 4080.
- [ ] A test PVC on the default `StorageClass` binds, and its data survives pod deletion.
- [ ] Namespaces `ollama`, `openviking`, and `hermes` exist.
- [ ] The `deploy/` layout and `deploy/README.md` are committed with a documented bootstrap order.
- [ ] Re-running the install scripts on a configured host makes no changes and exits 0.
- [ ] After `wsl --shutdown` and a restart, the node returns to `Ready` and the GPU smoke test passes.
