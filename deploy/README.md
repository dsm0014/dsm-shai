# deploy/

Declarative manifests for the dsm-shai stack. One directory per concern; each is a Kustomize root that a Flux `Kustomization` (spec 10) can point at directly. No secrets are committed (public repo): ciphertext only, see spec 07.

| Directory | Contents | Spec |
|-----------|----------|------|
| `platform/` | namespaces, `RuntimeClass nvidia`, NVIDIA device plugin (HelmRelease), smoke tests | 01 |
| `ollama/` | Ollama inference | 02 |
| `openviking/` | OpenViking context service | 03 |
| `hermes/` | Hermes Agent | 04 |

Later specs add `istio/`, `litellm/`, `browser/`, `open-webui/` and `monitoring/`.

## Bootstrap order

1. **Windows**: copy `windows/wslconfig.example` to `%UserProfile%\.wslconfig` (step 2 does this if the file is absent). Keep the Windows NVIDIA driver current; do not install a Linux display driver in WSL.
2. **Host** (WSL, Debian/Ubuntu): `sudo scripts/install-all.sh`. It enables systemd in `/etc/wsl.conf`, installs the pinned tools (`kubectl`, `helm`, `flux`, `nvidia-ctk`; versions in `scripts/versions.env`), and installs and configures k3s. If it reports that `.wslconfig` or `/etc/wsl.conf` changed, run `wsl --shutdown` from Windows, restart WSL, and re-run it.
3. **Cluster contents**: `scripts/bootstrap-flux.sh` (spec 10) makes Flux apply `deploy/platform/` first. Before spec 10 exists, apply by hand: `kubectl apply -f deploy/platform/namespaces.yaml -f deploy/platform/runtimeclass-nvidia.yaml`, then install the device plugin: `helm repo add nvdp https://nvidia.github.io/k8s-device-plugin && helm upgrade --install nvidia-device-plugin nvdp/nvidia-device-plugin -n nvidia-device-plugin --version <chart version in scripts/versions.env> --set runtimeClassName=nvidia --set affinity=null`.
4. **Verify**: `scripts/30-verify.sh` (add `--idempotent` to also confirm that re-running the install scripts changes nothing).

Scripts are safe to re-run: every step checks current state first and prints `CHANGED: ...` only when it modifies something.

## Notes

- k3s runs with Traefik disabled (`/etc/rancher/k3s/config.yaml`); the Istio ingress gateway (spec 08) is the single entry point. servicelb stays at its default.
- The `nvidia` runtime is registered by k3s auto-detecting `nvidia-container-runtime` when it starts, not by running `nvidia-ctk runtime configure` against the generated containerd config (k3s regenerates it). `scripts/20-k3s.sh` restarts k3s once if the runtime is missing from that config.
- The default `local-path` StorageClass and its data directory (`/var/lib/rancher/k3s/storage`) come from k3s and live on the WSL ext4 volume. Do not point storage at `/mnt/c`.
- If pods cannot resolve DNS on WSL2, re-run with `K3S_RESOLV_CONF=<path to a resolv.conf with real nameservers> sudo -E scripts/20-k3s.sh`.
- Namespaces carry `kustomize.toolkit.fluxcd.io/prune: disabled` so Flux never deletes a namespace and its PVCs.
- `platform/tests/` is deliberately outside the `platform/` Kustomization; `scripts/30-verify.sh` applies and removes it.

## Teardown and rollback

- **Remove one workload**: delete its Flux `Kustomization` (or `kubectl delete -k deploy/<concern>`). PVCs and namespaces are retained by the prune annotation; delete them explicitly to discard data.
- **Roll back a bad change**: `git revert` the commit and let Flux reconcile (or `kubectl apply -k` / `helm rollback` before Flux exists).
- **Remove the cluster**: `sudo /usr/local/bin/k3s-uninstall.sh` (deletes all cluster state, including local-path volumes). Re-create it with `sudo scripts/install-all.sh`.
- **Revert host tooling**: remove `/usr/local/bin/{kubectl,helm,flux}`; `sudo apt-mark unhold nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools libnvidia-container1 && sudo apt-get remove nvidia-container-toolkit`.
