# CI checks

Running `make test` executes `bash scripts/check-all.sh`, which runs every script named `scripts/check-*.sh` and `scripts/check-*.py`. The repository maintainer runs `make test` in a fresh clone of every swarm pull request before it can merge.

## The checks

| Check               | What it enforces                     |
|---------------------|----------------------------------------|
| shell syntax        | bash scripts parse without errors       |
| shebangs           | scripts start with a correct interpreter line |
| python syntax       | Python files compile                    |
| json validity       | JSON files parse                       |
| yaml tabs           | YAML files contain no tab characters   |
| line endings        | files use LF line endings, no CRLF     |
| large files         | no file exceeds the size limit          |
| markdown links      | relative links in Markdown resolve      |
| kustomize references | resources named in kustomization exist  |
| makefile help       | every Make target has a help entry      |
| token patterns      | no secret-like tokens are committed     |
| task list lint      | task list items use valid checkbox syntax|
| spec consistency    | checks spec files for consistency (warns unless `STRICT=1`) |

## Adding a check

Put a new script in the `scripts` directory, named `check-<name>.sh` or `check-<name>.py`. Exit non-zero on a problem. Ensure it passes on the repository as it currently is before opening a pull request.
