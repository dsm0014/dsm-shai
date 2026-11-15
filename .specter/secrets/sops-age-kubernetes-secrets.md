# SOPS + age for Git-Committed Kubernetes Secrets

**Tags:** sops, age, secrets, kubernetes, encrypted_regex, spec-07

Source: getsops/sops and the getsops/docs repo (age, config-file, common-operations, advanced, reference pages). The sops repo README only points at the docs repo.

## age identities

- Encrypt to one or more age recipients with `--age <recipients>` or `SOPS_AGE_RECIPIENTS`. SSH `ssh-ed25519`/`ssh-rsa` public keys also work as recipients.
- Decryption finds the private key in this order: `SOPS_AGE_KEY_FILE`, `SOPS_AGE_KEY`, `SOPS_AGE_KEY_CMD`, otherwise `$XDG_CONFIG_HOME/sops/age/keys.txt` (Linux fallback `~/.config/sops/age/keys.txt`). The key file holds `AGE-SECRET-KEY-...` identities one per line, and `#` lines are comments.
- Add or remove recipients with `sops updatekeys <file>`.
- The private key (`*.agekey`, `keys.txt`) never goes in Git. This is already covered by the repo `.gitignore`.

## `.sops.yaml` creation rules

- The file must be named exactly `.sops.yaml`. It is searched from the **current working directory** upward (not from the target file's directory), and rules are evaluated in order, first match wins. `path_regex` is relative to the config file location.
- Passing `--age` or `SOPS_AGE_RECIPIENTS` on the command line bypasses the config file.
- Suggested dsm-shai rule:
  ```yaml
  creation_rules:
    - path_regex: deploy/.*secret.*\.ya?ml$
      encrypted_regex: '^(data|stringData)$'
      age: age1...   # comma-separated or list; include a backup recipient
  ```
- **`encrypted_regex: '^(data|stringData)$'`** is the docs' own Kubernetes example. It encrypts Secret values while leaving `metadata` (names, namespaces) readable, so diffs and reviews stay useful.
- Only one of the six value-selection options can be used per rule: `encrypted_regex`, `unencrypted_regex`, `encrypted_suffix`, `unencrypted_suffix`, `encrypted_comment_regex`, `unencrypted_comment_regex`.
- `mac_only_encrypted: true` computes the file MAC over only encrypted values, so unencrypted fields can be edited without breaking integrity. By default unencrypted values are part of the MAC and cannot be modified outside SOPS.
- Key groups plus `shamir_threshold` allow multi-party decryption. This is overkill for one host, but a second recipient (an offline backup key) is cheap insurance.

## Format caveats

- The file extension picks the store (YAML, JSON, ENV, INI), and decrypting requires the same type (or `--input-type`/`--output-type`).
- YAML anchors do not work (path-bound AEAD). Top-level arrays are unsupported (wrap them in a key). Multi-document YAML is supported, but the MAC covers the whole file.
- YAML is re-indented with 4 spaces by default (`stores.yaml.indent` or `--indent` to change it).

## Workflows

- Edit: `sops edit secret.enc.yaml` (decrypt, open `$EDITOR`, re-encrypt). Encrypt in place: `sops encrypt -i file.yaml`. Decrypt to stdout: `sops decrypt file.enc.yaml`.
- Stdin encrypt needs `--filename-override path/name.yaml` so the creation rule and store are chosen: `echo 'foo: bar' | sops encrypt --filename-override x.sops.yaml`.
- Apply without writing plaintext to disk: `sops decrypt secret.enc.yaml | kubectl apply -f -` (stdout is the default, so this follows from the docs' piping pattern).
- Run a process with secrets: `sops exec-env file 'cmd'` (environment only) or `sops exec-file file 'cmd {}'` (a FIFO by default, so plaintext never touches disk).
- Readable diffs in Git: `.gitattributes` with `*.yaml diff=sopsdiffer`, plus `git config diff.sopsdiffer.textconv "sops decrypt"`.
- Naming: keep a distinct suffix (for example `*.enc.yaml`) for encrypted manifests, and keep `*.dec.yaml` and `secrets.yaml` in `.gitignore`, which matches the repo's existing ignore rules.

## Notes

- Newer docs use `sops encrypt` / `sops decrypt` / `sops edit` subcommands. Older tutorials use `-e` / `-d`.
- No Kubernetes controller is involved here. Decrypt happens in the deploy script (spec 07). A GitOps operator (Flux's SOPS support) is a possible future step.
