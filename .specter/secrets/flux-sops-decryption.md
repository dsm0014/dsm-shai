# Flux: In-Cluster SOPS Decryption with age

**Tags:** flux, sops, age, secrets, gitops, kustomize-controller, spec-07, spec-10

Source: fluxcd.io `/flux/guides/mozilla-sops/` (raw markdown from the docs repo), plus the Kustomization `decryption` field from the kustomize-controller spec. Complements [[sops-age-kubernetes-secrets]], which covers the SOPS CLI side.

## How it works

kustomize-controller decrypts SOPS-encrypted manifests just before applying them, using keys from a Secret in the same namespace as the Kustomization (normally `flux-system`). The flow is: source-controller pulls the repo, kustomize-controller loads the key Secret, decrypts, and applies. Encrypted manifests are meant for this path and should never be applied with `kubectl`.

## age setup

```sh
age-keygen -o age.agekey        # prints the public key (age1...)
cat age.agekey | kubectl create secret generic sops-age \
  --namespace=flux-system --from-file=age.agekey=/dev/stdin
```

- The Secret key name **must end in `.agekey`** to be detected as an age key. OpenPGP keys use `*.asc`, Vault uses `sops.vault-token`, AWS KMS uses `sops.aws-kms`.
- The Secret can hold several keys. SOPS tries each until one decrypts, which gives a simple rotation path (add the new key, re-encrypt, then remove the old one).
- Encrypt with `sops --age=<pubkey> --encrypt --encrypted-regex '^(data|stringData)$' --in-place secret.yaml`. In a repo-level `.sops.yaml`, use `age: <pubkey>` in `creation_rules` (the guide only shows the `pgp:` form, so the age form is inferred from the SOPS docs).

## Kustomization wiring

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: {name: secrets, namespace: flux-system}
spec:
  interval: 10m
  sourceRef: {kind: GitRepository, name: flux-system}
  path: ./clusters/dsm-shai/secrets
  prune: true
  decryption:
    provider: sops
    secretRef: {name: sops-age}
```

- `sops` is the only provider. `decryption.serviceAccountName` is for secret-less cloud KMS auth and is not needed with age.
- CLI form: `flux create kustomization ... --decryption-provider=sops --decryption-secret=sops-age`.
- Per-resource opt-out annotation: `kustomize.toolkit.fluxcd.io/decrypt: Disabled`.

## Rules and gotchas

- Encrypt only `data` and `stringData`. Encrypting `metadata`, `kind` or `apiVersion` is not supported by kustomize-controller.
- **Public key is enough to create files, not to edit them.** SOPS computes a MAC over all values, so editing an existing file needs the private key. With only the public key, delete and recreate the file.
- **`encrypted_regex` conflict with patches:** if a Kustomize patch adds plaintext fields that match the file's `encrypted_regex`, SOPS fails at decrypt time. Put secret values in the patch itself (patches are decrypted first), or keep secrets in standalone Secret manifests.
- Do not inject secret values into Pod env through patches. The guide's example is explicitly a bad practice and only illustrates merging behaviour.
- The guide has small inconsistencies (`sops-pgp` vs `sops-gpg` names, "`spec.provider`" where the field is `spec.decryption.provider`). The field names in the Kustomization spec are authoritative.
- Back up the key Secret offline. The in-cluster copy is the only decryption key unless you keep `age.agekey` elsewhere.

## Notes for dsm-shai

- Replaces the decrypt-and-apply path of spec 07's `scripts/apply-secrets.sh` (which becomes a break-glass tool) once spec 10 lands. `bootstrap-flux.sh` creates `sops-age` from the key kept outside the repo.
- For a public GitHub repo, the ciphertext is world-readable and permanent, so the age key is the only protection. See spec 10 for guardrails (secret scanning, rotation on exposure).
- The Kustomization that holds secrets must precede workloads that mount them, via `dependsOn` (see [[flux-kustomization-and-helmrelease]]).
