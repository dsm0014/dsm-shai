# CI checks

`make test` runs `bash scripts/check-all.sh`, which runs every script named `scripts/check-*.sh` and `scripts/check-*.py` (each one runs even if an earlier one fails), then the offline unit tests for the LiteLLM, nightly specter, swarm, repo maintainer and Claude Haiku jobs. The repo maintainer runs `make test` in a fresh clone of every swarm pull request before it can merge, so a check that fails on the repository as it stands blocks every later pull request.

Run all checks with `make check`, or a subset with `make check CHECK=<part of a script name>`. Run one by hand from the repository root, for example `bash scripts/check-shebangs.sh` or `python3 -I scripts/check-json-valid.py`.

| Check | What it enforces |
|---|---|
| shell syntax | Every tracked `.sh` file parses with `bash -n`. |
| shebangs | The first line of every tracked `.sh` file starts with `#!`. |
| python syntax | Every tracked `.py` file compiles, with or without a byte-order mark. |
| json validity | Every tracked `.json` file parses as JSON. |
| yaml tabs | No tracked YAML file contains a tab character. |
| line endings | Tracked `.sh`, `.py`, `.yaml`, `.yml`, `.md` and `.json` files use LF line endings, because CRLF breaks shell scripts under WSL. |
| large files | No tracked file is larger than `CHECK_MAX_BYTES` (default 1000000). |
| markdown links | Every relative link in a tracked `.md` file points to an existing file. |
| kustomize references | Every `.yaml`, `.yml`, `.json`, `.sh`, `.py`, `.txt` or `.md` file named in a tracked `kustomization.yaml` exists relative to that file's directory. |
| makefile help | Every `.PHONY` target in the Makefile has a help comment, and every help target is listed in `.PHONY`. |
| token patterns | No GitHub or Anthropic credential-shaped string appears in a tracked text file. |
| task list lint | Each swarm task line in `.specter/tasklist.md` names 1 to 3 repository paths, none of them protected, has no owner-only marker in its tag, and does not sit under a heading that marks it as not yet approved. |
| spec consistency | Each `specs/NN-name.md` has a `**Status:**` line and an index row that agree, and a DONE spec has no unchecked box. It only warns (`WARN path: message`, exit 0) unless `STRICT=1` is set. |
| sops | Every tracked `*.sops.yaml` is real SOPS ciphertext, and no plaintext key material appears in tracked files. |

## Adding a check

1. Put a script named `scripts/check-<name>.sh` or `scripts/check-<name>.py` in `scripts/`. Start it with a shebang line and a comment line saying what it enforces.
2. Run from the repository root, list files with `git ls-files`, and use no network.
3. Print one line per problem as `path: message` and exit 1 when there is a problem. Print `OK <check name>` and exit 0 when clean.
4. It must pass on the repository as it is today, because `make test` runs it on every pull request from then on. A check that cannot yet pass should only warn, as spec consistency does.
5. Add a row to the table above. `scripts/check-all.sh` picks the script up by its name, so nothing else needs registering.
