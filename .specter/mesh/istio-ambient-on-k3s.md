# Istio Ambient Mode on k3s: Platform Prerequisites

**Tags:** istio, ambient, k3s, cni, ztunnel, helm, spec-08

Source: istio.io/latest/docs/ambient/install/platform-prerequisites (taken from `istio/istio.io` master markdown, which may differ slightly from the rendered v1.32 page).

## Key finding: platform value instead of hand-set paths

For k3s with its **bundled CNI (flannel)**, Istio provides built-in overrides, so set the platform value rather than hard-coding paths:

```bash
helm install istio-cni istio/cni -n istio-system --set profile=ambient --set global.platform=k3s --wait
# or
istioctl install --set profile=ambient --set values.global.platform=k3s
```

This corrects the dsm-shai spec 08 wording, which hard-codes `cniBinDir=/var/lib/rancher/k3s/data/current/bin` and `cniConfDir=/var/lib/rancher/k3s/agent/etc/cni/net.d`. Prefer `global.platform=k3s` and record the resulting resolved paths in `deploy/istio/README.md`.

## Overriding paths

- k3s lets you override CNI directories (see docs.k3s.io CLI reference).
- With a **custom, non-bundled CNI**, k3s does not set CNI paths for containerd, so containerd uses its defaults `/etc/cni/net.d` and `/opt/cni/bin`. In that case do NOT set `global.platform=k3s`, and pass the paths explicitly:
  ```bash
  helm install istio-cni istio/cni -n istio-system --set profile=ambient --wait \
    --set cniConfDir=/etc/cni/net.d --set cniBinDir=/opt/cni/bin
  ```
  (istioctl: `values.cni.cniConfDir`, `values.cni.cniBinDir`).
- If a node's `/var/lib/rancher/k3s/agent/etc/containerd/config.toml` sets `bin_dir`/`bin_dirs` and `conf_dir`, containerd uses those instead, so use them.
- When running k3s with Traefik, the docs' k3d example disables it (`--disable=traefik`) to avoid clashing with Istio ingress gateways.

## What the page does not cover

- No kernel, iptables or WSL2 requirements appear on this page. Ambient traffic redirection on a WSL2 kernel remains the unverified risk called out in spec 08. Check the ztunnel traffic-redirection and CNI troubleshooting pages and test on the real host.
- The Cilium notes (`cni.exclusive=false`, no BPF masquerade, a CiliumClusterwideNetworkPolicy allowing `169.254.7.127/32` for kubelet probes) do not apply to the flannel default, but they matter if the CNI is ever swapped.

## Other platforms on the page (not relevant)

GKE (`global.platform=gke`, ResourceQuota for `system-node-critical`), EKS pod security groups, k3d (`global.platform=k3d`), MicroK8s, minikube and OpenShift each need their own `platform` value. The pattern is the same: nonstandard CNI paths are handled through `global.platform`.

## Health-probe detail worth knowing

Ambient uses the link-local SNAT address `169.254.7.127` to identify kubelet health probes. Default-deny NetworkPolicies on a CNI that does not exempt it can break probes. This is the reason spec 08 keeps baseline NetworkPolicies minimal.
