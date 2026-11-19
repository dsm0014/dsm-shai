cd /workspace && make hermes-task
```

**GitHub REST call that opens the pull request:**

- Method: `POST`
- Endpoint: `POST /repos/{owner}/{repo}/pulls` on `https://api.github.com`
- Required JSON body fields: `title`, `head`, `base`, `body`
- Headers:
  - `Authorization: Bearer $GITHUB_TOKEN` (read the token from the environment variable; never write a literal token)
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`

No GitHub token is provisioned in the pod yet (see the nightly job section), so `$GITHUB_TOKEN` will be empty until one is added.

Example command:

```bash
curl -sS -X POST "https://api.github.com/repos/{owner}/{repo}/pulls" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -d @pr.json
```

Example request body (`pr.json`; `{head-branch}` and `{base-branch}` are placeholders, not real branch names):

```json
{
  "title": "{title}",
  "head": "{head-branch}",
  "base": "{base-branch}",
  "body": "{description}"
}
```

## Nightly specter job (spec 11)

A nightly job that evaluates the owner's `claude-specter` repository against open-source equivalents on GitHub, then either writes improvement specs (Mode A) or implements one (Mode B), opens a pull request and merges it when the guardrails pass. **It is built but inert:** `NIGHTLY_REPO` is empty, there is no token, and the cron entry is not registered. Until both exist, `run.sh` exits 0 with the audit line `not configured`.

| Part | Where |
|---|---|
| Scripts and prompts (source) | `deploy/hermes/jobs/nightly-specter/` |
| In the pod (read-only ConfigMap `hermes-nightly-specter`) | `/opt/jobs/nightly-specter/` |
| State: lock, `runs/<date>.json`, `audit.jsonl`, `digest.log`, `metrics.prom` | `/opt/data/nightly-specter/` (PVC) |
| Clone and scratch | `/workspace/claude-specter`, `/tmp` (lost on restart; an interrupted run is abandoned) |
| Settings (ConfigMap `nightly-specter-env`) | `NIGHTLY_ALLOWED_REPOS` (isolation guard: the job refuses any `NIGHTLY_REPO` not listed, in `run.sh` and `gh_api.repo()`; add the real repo here at go-live), `NIGHTLY_REPO` (owner/name; `dsm0014/claude-specter-auto`, the private reh
<!-- INPUT TRUNCATED: the source ends mid-sentence at "the private reh". The remainder was not provided and must be restored from the original file before this content is used. -->
