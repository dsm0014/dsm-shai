# CI checks

The `make test` command runs `bash scripts/check-all.sh`, which executes every script named `scripts/check-*.sh` and `scripts/check-*.py`. The repository maintainer runs `make test` in a fresh clone of every swarm pull request before it can merge.

| Check               | What it enforces                                                                 |
|---------------------|---------------------------------------------------------------------------------|
| shell syntax        | Valid shell syntax in scripts                                                   |
| shebangs           | Correct shebang lines in executable files                                        |
| python syntax       | Valid Python syntax in `.py` files                                               |
| json validity       | Valid JSON syntax in `.json` files                                               |
| yaml tabs           | Consistent indentation (tabs) in YAML files                                     |
| line endings       | Unix-style (`\n`) line endings                                                    |
| large files         | Files exceeding 100 KiB are flagged                                              |
| markdown links      | Valid and reachable links in Markdown files                                      |
| kustomize references | Valid references in Kustomize manifests                                          |
| makefile help       | Proper formatting of `make help` output                                         |
| token patterns      | Consistent naming patterns in code tokens                                        |
| task list lint      | Properly formatted task lists in Markdown files                                  |
| spec consistency    | Consistent spec structure (warns unless `STRICT=1` is set)                        |

## How to add a check

To add a new CI check:
1. Place a script in the `scripts/` directory, naming it `check-*.sh` or `check-*.py`
2. Ensure the script exits with a non-zero status on any failure
3. Verify the script passes on the repository as-is before submitting
