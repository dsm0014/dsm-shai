# CI checks

`make test` runs `bash scripts/check-all.sh`, which executes every script named `scripts/check-*.sh` and `scripts/check-*.py`. The repository maintainer runs `make test` in a fresh clone of every swarm pull request before merging.

| Check            | What it enforces                                                                 |
|------------------|-----------------------------------------------------------------------------------|
| shell syntax     | Valid POSIX shell syntax in all shell scripts.                                    |
| shebangs        | Correct shebang lines (`#!/bin/sh` or `#!/bin/bash`) in executable files.       |
| python syntax    | Valid Python 3 syntax in all Python files.                                       |
| json validity    | Well-formed JSON in all `.json` files.                                          |
| yaml tabs        | **No** tab characters in YAML files (enforces YAML spec compliance).             |
| line endings     | Unix-style (`\n`) line endings in all text files.                                |
| large files      | Files exceeding 100 KiB trigger a warning (no hard failure).                      |
| markdown links   | Valid and reachable links in all Markdown files.                                 |
| kustomize refs  | Correctly formatted references in Kustomize manifests.                              |
| makefile help    | Proper formatting of `make help` output.                                          |
| token patterns   | Consistent naming patterns in code tokens (e.g., `snake_case` for variables).    |
| task list lint   | Valid Markdown task lists (e.g., `- [ ]` or `- [x]` format).                       |
| spec consistency | Warns if files deviate from documented specifications (fails only if `STRICT=1`).|

## How to add a check

Put a new script in `scripts/` named `check-<name>.sh` or `check-<name>.py`. Ensure it exits with a non-zero status on any problem, and confirm it passes on the repository as-is.
