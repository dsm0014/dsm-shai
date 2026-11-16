# GitOps with Flux (spec 10)

Flux 2.10.0 (pinned components, `clusters/dsm-shai/flux-system/gotk-components.yaml`) reconciles `main` of this public repository. Only the source, kustomize and helm controllers are installed. Bootstrap is idempotent: `scripts/bootstrap-flux.sh`.

## Stages

Each stage is a Flux `Kustomization` in `clusters/dsm-shai/`. A stage applies only after the stages it depends on are Ready.

| Stage | Path | Depends on |
|---|---|---|
| `platform` | `deploy/platform` (namespaces, RuntimeClass, device plugin) | none |
| `secrets` | `deploy/secrets` (SOPS, decrypted in-cluster with `sops-age`) | platform |
| `monitoring` | `deploy/monitoring` (kube-prometheus-stack) | secrets |
| `istio` | `deploy/istio` (ambient mesh) | monitoring |
| `inference` | `deploy/ollama` | istio |
| `litellm` | `deploy/litellm` | inference, istio |
| `openviking` | `deploy/openviking` | litellm, secrets |
| `mesh-policies` | `deploy/istio/policies` | istio, litellm, openviking, inference |
| `monitoring-extras` | `deploy/monitoring/extras` | monitoring, istio |
| `gpu-exporter` | `deploy/monitoring/gpu-exporter` | monitoring, platform |

**Not yet on `main`:** `litellm`, `openviking`, `mesh-policies`, `monitoring-extras` and `gpu-exporter` are on the feature branches (see `specs/00-index.md`). Hermes, Open WebUI and the backup have no stage yet. They are applied by hand today and will need stages after the merge.

## Secrets

SOPS with age (`.sops.yaml`, `encrypted_regex: ^(data|stringData)$`). The decryption key is the `sops-age` Secret in `flux-system`. Workflow in `docs/secrets.md`. Break-glass apply in `scripts/apply-secrets.sh`.

## Secret scanning (before commit and in CI)

- `.pre-commit-config.yaml`: gitleaks (v8.21.2) and `scripts/check-sops.sh`.
- `ci/secret-scan.workflow.yml`: gitleaks action and `scripts/check-sops.sh` on every push and pull request. **Not active yet:** GitHub refused to create the workflow with the current `gh` token (it lacks the `workflow` scope). To activate it, run `mkdir -p .github/workflows && cp ci/secret-scan.workflow.yml .github/workflows/secret-scan.yml`, then push with a token that has the `workflow` scope.
- `scripts/check-sops.sh`: every tracked `*.sops.yaml` (except the `.sops.yaml` config) must have a `sops:` block and `ENC[AES256_GCM` ciphertext. Tracked files must not contain LiteLLM, OpenViking or age private-key patterns. Verified: passes on the current tree, and a planted key fails the check.

## Tests (2026-11-16)

| Test | Result |
|---|---|
| `flux suspend` / `resume` on the `istio` stage | suspended state shown; resumed and reapplied the same revision (`main@0271961c`) |
| Controller memory (`kubectl top`) | helm 59 Mi, kustomize 107 Mi, source 82 Mi (limit 512 Mi each) |
| Deliberate break (a bad Istio value blocks downstream) | **not run**: it needs a push to `main` |
| `git revert` rollback | **not run**: it needs a push to `main` |
| Egress REGISTRY_ONLY for Flux | **n/a**: Flux's own egress is handled by the NetworkPolicies in `flux-system` (`allow-egress`, `allow-scraping`, `allow-webhooks`) |

The two tests that need a push to `main` are left for when you decide to merge. Running them on a throwaway branch would not exercise the real reconciliation.

## Flux's own network policies

`flux-system` already has three NetworkPolicies (`allow-egress`, `allow-scraping`, `allow-webhooks`). They are not changed here.

## Suspended stage (2026-11-16)

`platform` is **suspended** on purpose. Its manifest on `main` lacks the ambient namespace labels, and Flux would remove them every 10 minutes (see `deploy/istio/README.md`). After `feat/istio-mesh` is merged, run `flux resume kustomization platform`.

## Operating

```sh
flux get kustomizations                 # all stages
flux reconcile kustomization <name>     # force a stage
flux suspend kustomization <name>; flux resume kustomization <name>   # pause a stage during manual work
```
