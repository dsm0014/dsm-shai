# Flux: Bootstrap, Sources, Components, Repo Layout and Egress

**Tags:** flux, gitops, bootstrap, oci, networkpolicy, resources, spec-10

Source: fluxcd.io installation, bootstrap (generic Git, GitHub), configuration (optional components, air-gapped, proxy, bootstrap customization, vertical scaling), `guides/repository-structure`, `cheatsheets/oci-artifacts`, plus the source-controller `gitrepositories`/`ocirepositories` specs and `flux2` NetworkPolicy manifests (all raw markdown). The service-mesh remarks at the end are inference, not documented Flux behaviour. Flux 2.x, with Kubernetes 1.35+ officially supported (older versions may work).

## Bootstrap options

`flux bootstrap` is idempotent (re-running upgrades). It commits `clusters/<path>/flux-system/{gotk-components.yaml,gotk-sync.yaml,kustomization.yaml}` and then syncs from it, so Flux manages itself through the `flux-system` Kustomization (`prune: true`, `sourceRef: GitRepository/flux-system`). Upgrades, patches and config changes are then git commits, or a re-run of bootstrap with a newer CLI. The person bootstrapping needs cluster-admin and **push access** to the repo.

```sh
# GitHub: PAT on the workstation only; --token-auth stores it in the cluster as Secret flux-system
export GITHUB_TOKEN=<pat>
flux bootstrap github --token-auth --owner=<user> --repository=<repo> \
  --branch=main --path=clusters/dsm-shai --personal

# Generic Git over SSH: deploy key (read-only is enough unless using image automation)
flux bootstrap git --url=ssh://git@host/org/repo --branch=main \
  --private-key-file=key --path=clusters/dsm-shai
```

- GitHub fine-grained PAT permissions for an existing repo: Administration read-only, Contents read/write, Metadata read-only (Administration read/write if using `--token-auth=false`, which has Flux create an SSH deploy key). A classic PAT needs `repo`. A new repo is created private unless `--private=false`. A GitHub App secret (`flux create secret githubapp`) gives short-lived tokens instead of a user-tied PAT.
- With `--token-auth` the PAT becomes the cluster's git credential. **For a public repo this is unnecessary**: the in-cluster read does not need credentials, so either drop `secretRef` from the `GitRepository` in `gotk-sync.yaml` and delete the `flux-system` Secret after bootstrap, or skip `flux bootstrap` entirely. Instead, run `flux install --components=... --export > gotk-components.yaml`, commit it with a hand-written `GitRepository` (no `secretRef`) and `Kustomization`, and apply once. That keeps any write token out of the cluster altogether, at the cost of upgrading by re-exporting.
- Useful flags: `--interval` (default 1m), `--components`, `--components-extra`, `--network-policy`, `--cluster-domain`, `--registry`/`--registry-creds`/`--image-pull-secret`, `--commit-message-appendix`, `--toleration-keys`, `--force`.

## Components and footprint

```sh
flux bootstrap ... --components source-controller,kustomize-controller,helm-controller   # drop notification-controller
```

- Default set: source, kustomize, helm and notification controllers. Minimum viable: source plus kustomize. Image reflector/automation controllers and source-watcher are off unless `--components-extra`.
- Notification-controller is only needed for Alerts, Providers and webhook Receivers. Helm-controller is only needed for `HelmRelease`.
- Upstream manifests give each controller about 50-100m CPU and 64Mi memory requests, with 1 CPU and 1Gi limits. Idle use is far below the limits, but the 1Gi limits are loose for a node that shares 24GB with Ollama, so tighten them (for example 256-512Mi) with a patch.
- Customise in `clusters/<name>/flux-system/kustomization.yaml` using `patches` (args like `--concurrent`, resources, env). Commit the three files before first bootstrap, or edit and push afterwards.
- Source-controller keeps artifacts in an emptyDir, so a restart re-fetches (fine for a small repo). Optionally mount a PVC at `/data`.

## GitRepository and OCI sources

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata: {name: flux-system, namespace: flux-system}
spec:
  interval: 1m0s
  url: https://github.com/<user>/dsm-shai     # scp-style git@host:repo is not supported
  ref: {branch: main}                          # default branch is "master" if omitted
  # secretRef: omitted for a public repo
  ignore: |
    /*
    !/clusters
    !/deploy
```

- `ref` accepts `branch`, `tag`, `semver`, `name` or `commit`. `ignore` uses `.gitignore` syntax (also `.sourceignore` files), so docs and specs do not trigger reconciles.
- Credentials (if any) live in the Secret named by `secretRef`: SSH `identity`+`known_hosts`; HTTPS `username`+`password` (PAT); `bearerToken`; `ca.crt`; mTLS `tls.crt`/`tls.key`. `proxySecretRef` sets a per-object proxy.
- **OCI alternative (no Git remote):** `flux push artifact oci://<registry>/<repo>/manifests:<sha> --path=./clusters/dsm-shai --source=<url> --revision=<branch>@sha1:<sha>`, then `flux tag artifact ... --tag latest`. Consume it with an `OCIRepository` (`url: oci://...`, `ref.tag`/`semver`, `secretRef`, `insecure: true` for plain HTTP) as the Kustomization's `sourceRef`. `flux bootstrap` itself supports only Git providers, so OCI-only setups use `flux install` plus hand-applied source and Kustomization, or the Flux Operator (`FluxInstance` with `sync.kind: OCIRepository`). Cosign and Notation verification are supported.

## Repository layout (from the docs and the example repo)

```
clusters/dsm-shai/        flux-system/ (generated), infrastructure.yaml, apps.yaml  (Flux Kustomizations)
infrastructure/controllers/   namespaces, HelmReleases/OCIRepositories (mesh, device plugin)
infrastructure/configs/       CRs needing the controllers' CRDs (gateways, policies)
apps/...
```

- One `--path=clusters/<name>` per cluster. Every Kustomization YAML added under it is picked up by the `flux-system` Kustomization.
- Chain used by the example repo: `infra-controllers` (`wait: true`) then `infra-configs` (`dependsOn: infra-controllers`) then `apps` (`dependsOn: infra-configs`, `wait: true`), with `interval: 1h`, `retryInterval: 2m`, `timeout: 5m`. Without `wait: true` or `healthChecks`, `dependsOn` only waits for apply, not health. Details in [[flux-kustomization-and-helmrelease]].
- The docs say explicitly that this ordering can ensure a mesh proxy injector runs before workloads that need it. dsm-shai's `deploy/<concern>/` directories can be the Kustomization paths directly.

## Egress, NetworkPolicy and air-gapped use

- Bootstrap installs three NetworkPolicies in `flux-system`: `allow-egress` (all egress, plus ingress from the same namespace), `allow-scraping` (TCP 8080 from anywhere) and `allow-webhooks` (TCP 9292 to notification-controller). The artifact server (source-controller port 80) is therefore only reachable inside `flux-system`. `--network-policy=false` removes them (not recommended).
- If egress is restricted, allow: source-controller to the Git host, registry and chart repos (github.com, ghcr.io, and the Helm/OCI hosts used); kustomize-controller and helm-controller to the Kubernetes API and to source-controller port 80.
- `--cluster-domain` must match the cluster's domain (default `cluster.local`) or artifact URLs break.
- Proxy: patch `HTTPS_PROXY`/`NO_PROXY` into all Flux controllers (`NO_PROXY` must include `.cluster.local`, `.svc` and the `kubernetes` Service IP), or use `ALL_PROXY=socks5://...` for SSH Git on source-controller only.
- Air-gapped: mirror the controller images (`flux install --export | grep ghcr.io`, then `crane copy`) and bootstrap with `--registry`, `--registry-creds`, `--image-pull-secret`. Git, registry and Helm repos must be mirrored internally too.

## Inference for the Istio design (not documented by Flux)

- The docs have no Istio page. `flux-system` controllers use plain HTTP between each other and to the API server, so enrolling the namespace under STRICT mTLS with default-deny could break artifact fetches. Keeping `flux-system` out of the ambient mesh is the safe default (spec 08 then needs a ServiceEntry/egress allowance only if `REGISTRY_ONLY` is applied to its workloads).
- Mesh policy resources should be applied by a Kustomization that `dependsOn` the services they protect, last in the chain, so a policy mistake never blocks Flux itself.

## Notes for dsm-shai

- The public repo means the Git source is unauthenticated. See spec 10 for the secret-scanning guardrails, and [[flux-sops-decryption]] for the age key handling.
