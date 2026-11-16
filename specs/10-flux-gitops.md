# Spec 10 — GitOps with Flux

**Status:** IN PROGRESS (bootstrap and stage Kustomizations reconciled from main; secret scanning, suspend/resume and rollback tests and the deploy README pending)

## Purpose
Make the git repo the single source of truth for cluster state by running Flux on the single-node k3s cluster. Flux replaces the hand-run install and apply scripts with ordered, health-gated reconciliation (`dependsOn`), decrypts SOPS secrets in-cluster, and reverts drift. Depends on spec 01 (cluster) and reshapes how specs 02-09 are delivered and how spec 07 handles secrets. Specs 02-09 keep their requirements. Only the delivery mechanism changes.

## Behavior

**Components and footprint**
- Install only the controllers needed: source-controller, kustomize-controller and helm-controller. Notification-controller (default-on upstream) and the image automation controllers are omitted via `--components source-controller,kustomize-controller,helm-controller`. Controller memory limits are tightened (for example 256-512Mi, versus the 1Gi upstream limits) with a patch in `clusters/dsm-shai/flux-system/kustomization.yaml`. The pinned Flux version is recorded in the repo.
- Measured controller memory is recorded and stays within the cluster budget alongside the mesh (spec 08), so Ollama with the 14B model still loads (spec 02).
- The `flux` CLI is installed by `scripts/` with a pinned version, like the other host tools.

**Bootstrap and source**
- Bootstrapping is one documented, idempotent script (`scripts/bootstrap-flux.sh`). It installs the controllers, creates the `flux-system` sync and the SOPS decryption Secret, and can be re-run safely.
- The repo is public on GitHub, so the default Git source is that public repo over HTTPS with no read credential (no deploy key, no token in the cluster). Two supported paths: (a) `flux bootstrap github --token-auth` with a PAT on the workstation, after which the `secretRef` is removed from the `GitRepository` and the `flux-system` Secret deleted so the PAT does not stay in the cluster; or (b) no token at all, by committing `flux install --export` output plus a hand-written `GitRepository` and `Kustomization`, applied once. Any write token stays on the workstation and is never committed. A documented alternative for a private fork is an SSH deploy key or an OCI artifact (`flux push artifact` plus `OCIRepository`).
- Because the repo is public, whatever is committed is world-readable: manifests, hostnames, topology, and the SOPS ciphertext. This is acceptable only with the guardrails in the Secrets section below.
- `flux-system` stays outside the ambient mesh (controllers talk plain HTTP to the API server and to each other, and default-deny or STRICT mTLS there would break artifact fetches). Flux's own NetworkPolicies from bootstrap stay enabled, and `--cluster-domain` matches the cluster.
- Under the spec 08 `REGISTRY_ONLY` egress policy, the Git host (or registry) and the Helm/OCI chart hosts are explicitly allow-listed for the `flux-system` namespace and nothing else gains them.
- Flux manages itself through the `flux-system` Kustomization, so upgrading Flux is a commit that bumps the pinned version.

**Repository layout**
- `clusters/dsm-shai/` holds the Flux `Kustomization` entry points and per-cluster config. The existing `deploy/<concern>/` directories remain the workload manifests and Helm values from specs 01-09.
- Charts are consumed through `HelmRelease` resources, with chart and image versions pinned (no floating tags), and Kustomize overlays for plain manifests.

**Ordered rollout (`dependsOn`)**
- `dependsOn` only links resources of the same kind (Kustomization to Kustomization, HelmRelease to HelmRelease), so a Kustomization that must wait on a HelmRelease uses `wait: true` or `healthChecks` on the Kustomization that deploys it. The spec 08 rollout order is encoded as dependencies between Kustomizations and HelmReleases, each with `wait: true` or health checks, a `timeout` and `retryInterval`:
  1. `platform`: namespaces, `RuntimeClass nvidia`, the NVIDIA device plugin, storage classes (spec 01).
  2. `data`: the secrets Kustomization (decryption) first, then Postgres for LiteLLM.
  3. `monitoring`: kube-prometheus-stack (spec 06), which installs the Prometheus Operator CRDs, Prometheus and Grafana. Gated on `data` so the Grafana admin Secret is decrypted.
  4. `istio`: istio-base, then istio-cni, istiod, ztunnel, and the ingress gateway (spec 08). Each depends on the one before. CRD-bearing charts use `install.crds` and `upgrade.crds: CreateReplace`.
  5. `inference`: Ollama and its model-pull job (spec 02).
  6. `gateway`: LiteLLM (spec 09), then the browser MCP pod.
  7. `apps`: OpenViking (spec 03), Hermes (spec 04), Open WebUI (spec 05), and optional SearXNG.
  8. `observability`: DCGM exporter and the Grafana route (spec 06).
  9. `mesh-policy`: ALLOW policies, default-deny, STRICT mTLS and `REGISTRY_ONLY` egress, last and each gated on readiness of the services it protects.
- The `monitoring` stage comes before `istio`, `inference` and `gateway` on purpose. The kube-prometheus-stack CRDs (ServiceMonitor, PodMonitor, PrometheusRule) must exist before any stage applies a monitor, so those stages `dependsOn` `monitoring`.
- The mTLS PERMISSIVE-then-STRICT sequence from spec 08 is implemented as commits (or a suspended Kustomization that is resumed), not a manual step.
- A failed dependency blocks everything after it, and the failure reason is visible with `flux get kustomizations`.

**Secrets (SOPS + age, in-cluster)**
- Kustomizations that contain secrets set `spec.decryption.provider: sops` with a `secretRef` to a `sops-age` Secret in `flux-system`. The key name ends in `.agekey`.
- Public-repo guardrails: ciphertext in a public repo is permanent and copyable, so the age key is treated as the sole protection and is rotated (re-encrypt, new `sops-age` Secret) if it is ever exposed or if any plaintext secret was ever committed (history is then considered compromised, rotate the secret values too). A pre-commit hook and a CI check (for example gitleaks plus a check that every `*.sops.yaml` carries a `sops:` block) block plaintext secrets, `.env`, `*.agekey` and kubeconfigs. Personal data (home paths, email, hostnames beyond the placeholder domain) is kept out of committed files.
- The age private key is created in the cluster by `bootstrap-flux.sh` from the key outside the repo. It is never committed and never echoed. It stays backed up separately (spec 07).
- Only `data` and `stringData` are encrypted (`encrypted_regex`). Secret values are not injected through patches that would reintroduce plaintext matching the regex.
- Encrypted manifests are never applied with `kubectl`. Spec 07's `apply-secrets.sh` is reduced to a break-glass tool, and the normal path is a commit.

**Drift, updates and rollback**
- `prune: true` is on for application Kustomizations, so removing a manifest removes the object. Persistent volume claims and namespaces carry a prune-exempt annotation (`kustomize.toolkit.fluxcd.io/prune: disabled`) so data cannot be deleted by a mistaken commit.
- Manual changes made with `kubectl` are reverted at the next reconcile. The documented override is `flux suspend` and `flux resume`.
- HelmReleases use bounded `install` and `upgrade` remediation (retries, rollback on failure). A bad chart bump does not wedge the node.
- The reconcile interval is documented (default about 10m) along with `flux reconcile` for an immediate sync.
- Rollback is a `git revert` of the offending commit, and the cluster converges back to the previous state.

**Backup interaction**
- The spec 07 backup scope adds the `sops-age` Secret in `flux-system` (or the offline age key it comes from) as needed to rebuild, and the restore doc is rewritten so the rebuild is: install k3s, restore the age key, run `bootstrap-flux.sh`, and restore PVC data.

## Acceptance Criteria
- [ ] Flux is installed from pinned versions with only source, kustomize and helm controllers, and the measured controller memory is recorded and within budget.
- [ ] `scripts/bootstrap-flux.sh` takes a fresh k3s cluster to a fully reconciled stack, and re-running it makes no changes.
- [ ] Flux syncs from the public GitHub repo with no credential stored in the cluster, and no token, deploy key or age private key is committed.
- [ ] The pre-commit and CI secret scanning fails on an injected plaintext Secret and on an unencrypted `*.sops.yaml`, and passes on the clean repo, including a scan of the full git history.
- [ ] Reconciliation order follows the `dependsOn` chain above, verified by `flux get kustomizations` and `flux get helmreleases` showing each stage ready before the next starts.
- [ ] Deliberately breaking an upstream stage (for example a bad Istio value) blocks downstream stages and surfaces a clear error.
- [ ] An encrypted Secret committed to the repo is decrypted and applied by kustomize-controller, and no plaintext secret exists in git, in the working tree, or in Flux's source artifact.
- [ ] Editing a Deployment with `kubectl` is reverted at the next reconcile, and `flux suspend` allows a temporary override.
- [ ] Deleting a manifest from git removes the workload but not its PVC (prune-exempt).
- [ ] `git revert` of a bad HelmRelease bump restores the previous working release.
- [ ] Flux can reach the Git host or registry and chart repos under `REGISTRY_ONLY` egress, and no other workload can.
- [ ] A rebuild from scratch (wiped k3s, restored age key, bootstrap script, restored data) matches the previous cluster state and is documented in `docs/restore.md`.
- [ ] `deploy/flux/README.md` documents the source choice, bootstrap, layout, dependency order, secrets workflow and the override and rollback procedures.
