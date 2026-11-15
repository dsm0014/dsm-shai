# Flux: Kustomization and HelmRelease (dependsOn, Health, Prune, CRDs)

**Tags:** flux, gitops, kustomization, helmrelease, dependson, helm, spec-10

Source: fluxcd/kustomize-controller `docs/spec/v1/kustomizations.md` and fluxcd/helm-controller `docs/spec/v2/helmreleases.md` (the fluxcd.io pages are generated from these, and the website-repo paths 404). `dependsOn` details were cross-checked in the controller source. Flux release at time of reading: v2.10.0.

## API versions

`kustomize.toolkit.fluxcd.io/v1` (Kustomization), `helm.toolkit.fluxcd.io/v2` (HelmRelease), `source.toolkit.fluxcd.io/v1` (GitRepository, OCIRepository, HelmRepository, HelmChart, Bucket). The `v1beta*` and `v2beta*` versions are legacy.

## Kustomization essentials

- Required: `interval` (60s or more), `sourceRef` (GitRepository, OCIRepository, Bucket), `path`, `prune`. Each interval runs a server-side-apply dry-run, so drift is detected and corrected. A new source revision or a spec change reconciles immediately.
- `targetNamespace` sets the namespace on all objects, but the namespace must already exist.
- `timeout` covers build, apply and health checks. `retryInterval` applies to failed reconciles only (defaults to `interval`).
- Docs' production baseline: `interval: 60m`, `wait: true`, `timeout: 3m`, `retryInterval: 2m`, `prune: true`, `force: false`.

## dependsOn (ordering)

- A Kustomization with `dependsOn` is applied only after every listed Kustomization is `Ready=True` (observed generation current). Circular dependencies mean nothing is applied. A missing dependency fails the reconcile with "dependency not found".
- Entries are `{name, namespace?, readyExpr?}`. Namespace defaults to the dependent's own, and cross-namespace works.
- **Same kind only.** Kustomization depends on Kustomization, HelmRelease on HelmRelease. To make a Kustomization wait on a HelmRelease, put it in a Kustomization that has `healthChecks` (including a `HelmRelease` entry) or `wait: true`, then `dependsOn` that Kustomization.
- "Ready" for a dependency that has `wait: true` or `healthChecks` means those checks passed. This is what makes `dependsOn` a real ordering gate (for example, Istio's injector or CRDs exist before apps apply).
- `readyExpr` is a CEL expression (variables `dep`, `self`) that replaces the built-in readiness check, unless the `AdditiveCELDependencyCheck` feature gate is on.

```yaml
spec:
  dependsOn:
    - name: istio
  wait: true          # health-checks everything this Kustomization applies
  timeout: 10m
  retryInterval: 2m
```

## Health checks

- `wait: true` checks all applied resources and ignores `healthChecks`. `healthChecks` lists specific objects: built-in kinds (Deployment, DaemonSet, StatefulSet, PVC, Job, Service, CRD and others), Flux kinds (HelmRelease, GitRepository) and kstatus-compatible custom resources.
- `healthCheckExprs` adds CEL checks (`current`, `inProgress`, `failed`) for CRs that do not report kstatus. Order of evaluation: inProgress, failed, current.
- If a check fails or exceeds `timeout`, `Ready=False`, which blocks dependents.

## Prune, force and per-resource controls

- `prune: true` deletes objects removed from source, and everything if the Kustomization is deleted. Exempt a resource with `kustomize.toolkit.fluxcd.io/prune: disabled` (the docs suggest this for Namespaces, PVCs and PVs). `deletionPolicy`: `MirrorPrune` (default), `Delete`, `WaitForTermination`, `Orphan`.
- `force: true` replaces objects on immutable-field changes and can cause downtime. Prefer the per-resource annotation `kustomize.toolkit.fluxcd.io/force: enabled` and remove it afterwards.
- Other annotations: `kustomize.toolkit.fluxcd.io/ssa` (`Override|Merge|IfNotPresent|Ignore`) and `kustomize.toolkit.fluxcd.io/reconcile: disabled` (pause one object, with no apply and no prune).

## postBuild variable substitution

`postBuild.substitute` (inline) and `substituteFrom` (ConfigMap or Secret, `optional: true` allowed) fill `${var}` and `${var:=default}` in manifests. Inline beats `substituteFrom`, and later entries beat earlier ones. Quote numbers and booleans with a helper var (`quote: '"'`). Secrets used here must use `stringData`. Opt-out per object with `kustomize.toolkit.fluxcd.io/substitute: disabled`. Useful for a single `cluster-vars` ConfigMap (hostnames, sizes). Never put secrets in it in a public repo.

## Suspend and resume

`flux suspend|resume kustomization|helmrelease <name>`, or patch `spec.suspend` with `--field-manager=flux-client-side-apply`. Suspending stops applying new revisions and pauses drift correction. When resuming through git, remove the field rather than setting it to `false`. `flux reconcile ... ` forces an immediate sync.

## HelmRelease essentials

- Exactly one of `chart` (template that creates a HelmChart or OCIRepository) or `chartRef` (reference to an existing OCIRepository, HelmChart or ExternalArtifact). The docs recommend OCI charts with an `OCIRepository` as `chartRef` for production. Charts from classic HTTP repos use a `HelmRepository` plus `chart.spec` with `chart`, `version` (semver range) and `sourceRef`.
- `releaseName` defaults to `[targetNamespace-]name`, `targetNamespace` and `storageNamespace` default to the HelmRelease's own. Changing any of the three uninstalls the old release first. `install.createNamespace: true` creates the namespace.
- Values merge order: `valuesFrom` entries in order, then inline `values`, then any `targetPath` entries. Label referenced ConfigMaps and Secrets `reconcile.fluxcd.io/watch: Enabled` so changes reconcile at once. Changes to the merged values trigger an upgrade.
- `dependsOn` works HelmRelease to HelmRelease, with "Ready" meaning installed, up to date, tests passed (if enabled) and not currently reconciling.

## Install, upgrade and remediation

```yaml
spec:
  timeout: 5m
  install:
    crds: CreateReplace
    strategy: {name: RetryOnFailure, retryInterval: 5m}   # default is RemediateOnFailure
  upgrade:
    crds: CreateReplace
    strategy: {name: RetryOnFailure, retryInterval: 5m}
    remediation: {retries: 3, strategy: rollback}          # used with RemediateOnFailure
  driftDetection: {mode: enabled}
```

- `RemediateOnFailure` (default) uses `remediation.retries` (default 0, negative means infinite) with uninstall (install) or rollback (upgrade) between attempts. `RetryOnFailure` retries as an upgrade after `retryInterval` with no remediation, and the docs suggest it for StatefulSets and anything that cannot tolerate rollback (relevant to Postgres and Ollama).
- **CRDs:** Helm does not upgrade CRDs. `crds: Skip|Create|CreateReplace`, where `Create` is the default (never updates) and `CreateReplace` updates existing CRDs but never deletes them. Use `CreateReplace` for Istio and similar CRD-bearing charts.
- `driftDetection.mode`: `enabled` (corrects), `warn`, with `ignore` rules (for example `/spec/replicas`).
- `timeout` default is 5m, and per-action blocks override it. Large images (Ollama, GPU operator pieces) may need a higher value.
- Changing the chart name in `Chart.yaml` uninstalls the old release unless `upgrade.chartNameChangeStrategy: InPlaceUpdate`.
- `waitStrategy.name`: `poller` (default, kstatus) or `legacy`.

## Notes for dsm-shai

- Map the spec 08 rollout order onto a chain of Kustomizations: each infrastructure stage uses `wait: true` and the next lists it in `dependsOn`. Put the Istio charts in one Kustomization with a HelmRelease chain via HelmRelease `dependsOn` (base, cni, istiod, ztunnel, gateway).
- Mark PVCs and namespaces `prune: disabled` so a bad commit cannot delete Ollama weights, Postgres or OpenViking data.
- Remember [[open-webui-config]]'s `ENABLE_PERSISTENT_CONFIG=False`: Flux will revert manual changes to manifests, but app-level persisted settings are separate.
- Secrets decryption config is in [[flux-sops-decryption]].
