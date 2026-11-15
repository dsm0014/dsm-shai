# k3s: containerd Config, NVIDIA Runtime and Host Prep

**Tags:** k3s, containerd, nvidia, runtimeclass, gpu, dns, systemd, spec-01

Source: docs.k3s.io/advanced (raw `k3s-io/docs` `advanced.md`). The page has no WSL2, Traefik-disable or local-path sections. Those live on other k3s pages (packaged components, storage), which were not ingested.

## NVIDIA GPU support

1. Install the NVIDIA container runtime packages on the node (repo: nvidia.github.io/libnvidia-container).
2. Install or restart k3s. k3s auto-detects runtimes on the service `PATH`, and the supported alternative runtimes are `crun, lunatic, nvidia, nvidia-cdi, nvidia-experimental, slight, spin, wasmedge, wasmer, wasmtime, wws`.
3. Verify: `grep nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml`.

k3s ships `RuntimeClass` objects for every supported runtime. Either:
- set `--default-runtime nvidia` in the k3s CLI or config file, or
- set `runtimeClassName: nvidia` explicitly in each GPU pod spec.

GPU pods request `nvidia.com/gpu: 1` under `resources.limits` (provided by the NVIDIA device plugin, which is usually installed with the runtimeClass change). Typical env: `NVIDIA_VISIBLE_DEVICES=all`, `NVIDIA_DRIVER_CAPABILITIES=all`.

If the runtime is not detected, make sure it is in a standard `PATH` directory (`/usr/local/sbin`, `/usr/local/bin`, `/usr/sbin`, `/usr/bin`, `/sbin`, `/bin`).

## containerd configuration

- k3s generates `/var/lib/rancher/k3s/agent/etc/containerd/config.toml`. Do not edit it, because it is regenerated.
- Since the Feb 2025 releases (v1.31.6+k3s1, v1.32.2+k3s1) k3s bundles containerd 2.0, which prefers config **version 3**. Customise with a template in the same directory: `config-v3.toml.tmpl` (containerd 2.0) or `config.toml.tmpl` (containerd 1.7, config v2, still honoured when no v3 template exists).
- Extend the stock config instead of copying it:
  ```toml
  {{ template "base" . }}

  [plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.'custom']
    runtime_type = "io.containerd.runc.v2"
  ```
- Do NOT copy a prerendered `config.toml` into the template. Use `{{ template "base" . }}` or a full template based on the k3s defaults.
- Istio CNI needs these containerd/CNI directories (see [[istio-ambient-on-k3s]]).

## systemd and install script

- The install script detects systemd or openrc, then enables and starts the service. Logs: `journalctl -u k3s` under systemd.
- To install without starting: `curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true sh -`.
- WSL2 needs `systemd=true` in `/etc/wsl.conf` for this to work (not covered by this page).
- The default install bundles `local-path-provisioner`, `metrics-server`, `coredns` and `traefik` (plus its svclb). Traefik must be disabled with `--disable=traefik` for the Istio ingress design.

## DNS on WSL2

On start, each node checks `/etc/resolv.conf` and `/run/systemd/resolve/resolv.conf` for loopback, multicast or link-local nameservers. If neither file is usable, k3s warns and falls back to a stub resolver using `8.8.8.8` and `2001:4860:4860::8888`. WSL2 generates `resolv.conf` automatically, so pass `--resolv-conf <path>` if pods cannot resolve names. Customise CoreDNS through the `coredns-custom` ConfigMap in `kube-system` (`*.override` keys go into the main server block, `*.server` keys add server blocks).

## Other relevant notes

- CA certificates last 10 years with no auto-renew. Client and server certificates last 365 days and are renewed at startup when within 90 days of expiry.
- HTTP proxy: the install script copies `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` into `/etc/systemd/system/k3s.service.env`. k3s adds the pod/service CIDRs and cluster domain to `NO_PROXY` itself.
- SELinux, rootless mode and agentless servers are experimental or irrelevant for a single-node WSL2 install.
