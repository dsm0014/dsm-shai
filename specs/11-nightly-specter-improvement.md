# Spec 11 — Nightly Specter Improvement

**Status:** PARTIAL (job scripts, 33 local tests, proxy and policy manifests, alerts and Flux wiring are built and committed; the token, the proxy's first run, in-pod checks, the fork rehearsal and the cron entry are open; see deploy/hermes/README.md)

## Purpose

A nightly Hermes job evaluates the user's `claude-specter` repository, compares it with open-source equivalents on GitHub, and turns the improvement vectors into specs. On nights when an unimplemented improvement spec already exists, it implements one instead, tests it, and opens and merges the pull request. The target is `claude-specter` only, never `dsm-shai`, so Flux is not involved and no cluster state changes through this job. Depends on spec 04 (Hermes), spec 08 (mesh and egress), spec 09 (LiteLLM) and spec 10 (secrets delivery).

## Behavior

**Schedule and locking**
- A Hermes cron job (`hermes cron`) starts at 02:30 local time, once per night, inside a 02:30 to 05:30 window that avoids daytime GPU contention. A 90-minute wall-clock cap is enforced with `timeout` in the wrapper `deploy/hermes/jobs/nightly-specter/run.sh`.
- The wrapper takes `flock` on `/opt/data/nightly-specter/lock`. If held, it exits 0 and logs `skipped: locked`. Each run has a run ID and a state file `/opt/data/nightly-specter/runs/<date>.json`; a second non-dry run on the same date is refused.

**Mode selection (non-LLM, `select_mode.py`; the model never chooses)**
- The script clones `claude-specter`, reads `specs/` and parses `**Status:**` and the front-matter key `origin: nightly-improvement`. Mode B if at least one spec with that origin has Status TODO or PARTIAL; otherwise Mode A.
- If a pull request with branch prefix `nightly/` is open (including an implementation PR waiting for review), the result is `HOLD`: the run writes an audit entry and a digest line and does nothing else.

**Mode A: evaluate and author specs**
- Clone over HTTPS into `/workspace/claude-specter` (ephemeral; re-cloned each run). `inventory.py` (non-LLM) emits a JSON inventory of skills, agents, specs, file tree and sizes. The model sees chunks of at most 6K tokens, never the whole repo.
- Candidates come from the GitHub search API using the repo's topics (for example "claude code skills", "spec-driven development"): at most 5 repos, at least 50 stars, not archived, pushed within 12 months. Per repo fetch only the README and top-level tree. Record URL, licence SPDX id and fetch date. No code or prose is copied; a spec cites the repo and describes the idea in its own words.
- One `hermes -z` step per repo summarises features into a schema-validated JSON; one step derives improvement vectors; at most 3 new specs per night. `dedupe.py` drops vectors that overlap existing specs, open PRs or closed `nightly/` PRs.
- Each vector becomes a spec by following the `new-spec` procedure: the SKILL.md text and template are given to the model as prompt text. Claude Code skill machinery does not run in Hermes and quality is lower than in Claude Code. The spec number comes from a script. Each spec carries `origin: nightly-improvement`, `Status: TODO`, the source URLs and licence notes.
- Commit on `nightly/specs-YYYYMMDD`, open one PR with spec files and the index only, and merge through the guardrails.

**Mode B: implement one spec**
- Take the lowest-numbered improvement spec from `select_mode.py`. Branch `nightly/impl-<NN>-YYYYMMDD`. A script extracts the spec's file/path list into `allowed_paths.txt`; a spec without a parseable list is set to `Status: BLOCKED` in a PR of its own and nothing is implemented.
- Implement following the `do-spec` procedure (prompt text, local model). Edits go through a file-write tool restricted to the allowed paths. Run the repo's test command (found by `inventory.py`, for example `make test` or `scripts/validate.sh`); it must exit 0.
- The same PR updates the spec Status (DONE, or PARTIAL with unmet criteria listed) and its index row. Exactly one implementation PR per night.

**Step execution and verification**
- Every step is a separate `hermes -z "<exact prompt>"` from a versioned prompt file with numbered instructions and a required output format. After each step a non-LLM verifier checks the artefact: file exists, front matter and Purpose/Behavior/Acceptance Criteria present, `git diff --numstat` within caps and paths, JSON parses, tests exit 0. A failed step is retried once; a second failure aborts the run and discards the branch. Malformed tool-call JSON counts as a failed attempt. Only verifier results count as success.

**Egress (revisits the spec 08 hostname decision for this pod and these hosts only)**
- The hermes pod gets no direct internet route. A forward proxy (Squid, pinned by digest) in namespace `egress-proxy` is the only workload with internet egress. It allows CONNECT on 443 to `github.com`, `api.github.com`, `codeload.github.com`, `raw.githubusercontent.com` and `objects.githubusercontent.com` and nothing else, and logs denials. The allowlist is on the CONNECT target hostname, which works on any Squid build; Squid dials the allowed host itself, so a client that sends another SNI still reaches only GitHub. SNI inspection (`ssl_bump peek` and `splice`) needs an OpenSSL build of Squid, which the pinned Ubuntu image probably is not (GnuTLS), so it is optional and unverified. `REGISTRY_ONLY` and ServiceEntry are not relied on (ztunnel does not enforce them for unregistered hosts, `deploy/istio/README.md`). This deviates from spec 08's ServiceEntry-plus-waypoint mechanism; the owner chose Squid on 2026-11-17 after reviewing the alternatives, which are recorded with the revisit triggers in `deploy/istio/egress/README.md`.
- Hermes egress adds only the proxy on `:3128` to the existing DNS, LiteLLM and OpenViking rules (`deploy/hermes/egress-networkpolicy.yaml`). The proxy is reachable only from the hermes service account. The pod sets `NIGHTLY_HTTPS_PROXY`; the job wrapper exports `HTTPS_PROXY` and `NO_PROXY` (`.svc`, `.cluster.local`) from it, so interactive Hermes is not proxied. No `git config` is written (the home is the PVC); git takes its credential header from environment variables. Git uses HTTPS only. The allowlist lives in `deploy/istio/egress/` (the directory spec 08 names; it does not exist yet), minimal and reviewable.

**Credentials**
- A fine-grained token (a GitHub App installation token is preferred) limited to the single repository `claude-specter`: Contents read/write, Pull requests read/write, Metadata read. No Administration, no Workflows, 90-day expiry. Stored as `deploy/secrets/hermes-github.sops.yaml` (added to `deploy/secrets/kustomization.yaml`), delivered as env var `GITHUB_TOKEN` through `secretKeyRef` in the hermes namespace only. Never in a ConfigMap, log, prompt or OpenViking; scripts redact `ghp_` and `github_pat_` patterns. Hermes still has no Kubernetes API token.
- Rotation: create the new token, `sops edit`, commit, let Flux reconcile, delete the hermes pod, run the dry run, revoke the old token. Revocation in GitHub takes effect at once; the job then fails closed and alerts.

**Autonomous-merge guardrails (scripts or GitHub settings, never the model)**
- `guard.py` fails the run on: more than 400 changed lines or 12 files (Mode A: at most 3 spec files plus the index); any path outside the allowlist (Mode A: `specs/*.md` and `specs/00-index.md`; Mode B: only paths named in the spec); any change under `.github/`, any `*.sops.yaml` or `.env*`, the job's own files, or the guard and allowlist files; a branch not prefixed `nightly/`; a secret-scan hit.
- Required checks: if `claude-specter` has CI checks, merge needs them green (branch protection plus `gh pr merge --auto`). If it has none, `scripts/validate.sh` (markdown lint, front-matter check, repo tests) must pass locally and the audit entry records `no CI: local validation only`.
- One spec-authoring or one implementation PR per night, enforced by the state file and a GitHub query for `nightly/` PRs created today.
- Kill switches: `hermes pause`; a `.nightly-disabled` flag file on `main`, checked before each run; tightening branch protection on `main` to require review, which makes auto-merge fail and leaves the PR open.
- Audit log: append-only JSONL at `/opt/data/nightly-specter/audit.jsonl` (open with `O_APPEND`, never rewritten) plus a summary `remember` into OpenViking. Each entry has run ID, mode, PR URL, per-step verifier results, LiteLLM token usage for key `hermes`, and duration.
- Failure alert (no Alertmanager exists): the wrapper writes `metrics.prom` (`nightly_specter_last_success_timestamp`, `nightly_specter_last_run_status`, `nightly_specter_consecutive_failures`) served read-only on port 9101 and scraped by Prometheus, with an alert rule; every run also appends a line to the daily digest, which is the primary alert.

**Unattended merging and human override**
- Merges are unattended: no human reads a diff before it reaches `main`. Overrides: `git revert -m 1 <merge-sha>` on `claude-specter`, `hermes pause`, the `.nightly-disabled` flag, a branch-protection toggle, token revocation.
- Spec-only PRs auto-merge. Implementation PRs auto-merge only after `IMPL_PROBATION_NIGHTS` consecutive clean nights in the audit log (no failed verifier, no revert); default 7, resets on any failure or revert, and `0` gives full auto-merge from the first night. This default is a recommended safety margin, not a model decision, and the owner may set it to 0.

**Limits**
- 64K context (prompts under 16K, repo content chunked); 2 concurrent LLM calls, so steps run sequentially; the 180 s LiteLLM timeout means long output is split one section per call; `/workspace` is lost on restart, so an interrupted run is abandoned and its branch deleted by the next run. Fetched repo content is untrusted: prompts wrap it in delimiters and the guard stops any resulting out-of-scope diff.

**Amended statements (for this job only)**
- Spec 08: the hostname allowlist kept as default-deny is revisited for the hermes pod and the five GitHub hosts through the proxy; all else stays default-deny. Spec 04: egress "only" to DNS, LiteLLM, OpenViking and an explicit web allowlist now includes the proxy; the spec 04 line that the web allowlist uses `REGISTRY_ONLY` plus ServiceEntry is replaced by the proxy for this pod.
- Spec 10: "any write token stays on the workstation", "no credential stored in the cluster" and "nothing else gains" the Git host egress apply to Flux and `dsm-shai`. They are amended so that the hermes namespace alone holds a repo-scoped `claude-specter` token and reaches GitHub through the proxy. Flux still reads `dsm-shai` unauthenticated.
- Spec 09: Hermes holds `GITHUB_TOKEN` in addition to its LiteLLM and OpenViking keys.

## Acceptance Criteria

- [x] `select_mode.py` on fixture repos prints B for a repo with an `origin: nightly-improvement` TODO spec, A for one with only DONE or human specs, A when the only TODO spec lacks the origin marker, and HOLD when a `nightly/` PR is open.
- [x] `guard.py` exits non-zero with a named reason for a diff outside the allowlist, one over 400 lines or 12 files, one touching `.github/`, and a spec missing a required section or front matter.
- [ ] From the hermes pod, `https://api.github.com/rate_limit` succeeds through the proxy; `https://example.com` returns 403; direct egress without the proxy times out; a CONNECT to a non-allowlisted host is denied (a mismatched SNI is denied only with an OpenSSL-build Squid); no other pod can use the proxy. The proxy log shows each.
- [ ] The token cannot read or write any other repository (`gh api repos/<owner>/<other>` returns 403 or 404) and a push under `.github/workflows/` is rejected.
- [x] `run.sh --dry-run` produces a draft PR or local patch with a report, merges nothing, and the audit entry has `dry_run: true`.
- [x] A second run on the same date opens no PR and logs the one-PR-per-night limit; a concurrent launch logs `skipped: locked` and writes one audit entry.
- [ ] `hermes pause` before 02:30 results in no run at the next schedule time and `hermes resume` restores it; the `.nightly-disabled` flag also stops a run (the flag is tested locally; `hermes pause` is open).
- [x] A forced verifier failure leaves nothing merged and the branch discarded, writes an audit entry and a digest line, sets `nightly_specter_last_run_status` to failure, and increments `consecutive_failures`.
- [ ] `git grep -E 'ghp_|github_pat_' -- . ':!*.md'` is clean (checked), `deploy/secrets/hermes-github.sops.yaml` is ciphertext only, the pre-commit secret scan passes, and `kubectl get cm -n hermes -o yaml` contains no token.
- [x] With `IMPL_PROBATION_NIGHTS=7` and fewer than 7 clean nights, a Mode B PR stays open and the next night reports HOLD; with `0` it merges.
- [ ] An end-to-end run against a throwaway fork of `claude-specter` completes in Mode A (up to 3 valid specs merged in one spec-only PR) and in Mode B (one implementation PR, tests exit 0, spec Status updated) before the job is pointed at the real repo.
- [x] `deploy/hermes/README.md` documents the job, schedule, guardrails, revert procedure, token rotation and revocation, and the amended egress and credential statements in specs 04, 08, 09 and 10; `deploy/istio/egress/` holds the allowlist.
