# Spec 14 — Autonomous Repo Work via the Swarm

**Status:** IN PROGRESS

> **Amendments made while building (2026-11-19):** (1) workers return the complete new content of one file in a fenced block, not a diff: a 9B model writes unified diffs unreliably. The script writes the file, derives the diff with `git diff` and enforces `allowed_paths`, the forbidden list and the caps on that real diff (`diff_allowed` stays for diff-producing steps). (2) "Check off the task" means removing its line from the task list, per the repo convention that the list holds only work still to do. (3) The job lives in `deploy/hermes/jobs/swarm-repo-work/` (`make swarm-plan TASK=repo-work` resolves the `swarm-` prefix) and the code in `deploy/hermes/jobs/swarm/` (`pick_task.py`, `repo_work.py`, dispatched by `kind: repo_work`). (4) after the first live run (a worker saw only part of a long README and rewrote it, +30/-230, closed unmerged) two guards were added: a file larger than `SWARM_MAX_FILE_CHARS` (24000) is refused before any worker call, and a change deleting more than `SWARM_MAX_DELETE_PCT` (50) percent of a file fails; tasks must therefore target files a worker can see whole. (5) `SWARM_REPO_WORK` is `0` in the `swarm-env` ConfigMap until the owner flips it in a reviewed PR.

## Purpose

Let the Hermes swarm (spec 13) work through this repository's task list unattended: pick one eligible task, make the change on a branch with Haiku and local Qwen workers, prove it with scripts, and open a pull request for the owner to merge. The swarm never merges its own pull request. Depends on specs 11 (GitHub egress and token handling), 12 (Haiku wrapper) and 13 (swarm engine and caps).

## Behavior

**Eligibility (explicit opt-in only)**
- A task is eligible only if its line in `.specter/tasklist.md` carries the marker `[swarm]` (for example `- [ ] [swarm] Add a make hermes-task example ...`) and is not started (`[ ]`, not `[~]`). Unmarked tasks, tasks marked `[needs-owner]`, and anything under the headings "Needs you at the machine" and "Proposed, not decided" are never picked. The owner controls the queue by editing the marker.
- The task text must name its target files (a backtick path list) so `allowed_paths` is derived from the task, not invented by a model. A task with no file list is skipped with a digest line.
- Selection is a script (`pick-task.py`): the first eligible task in file order. No model picks the task.

**Isolation and guards (all fail closed)**
- The target repo must be in `SWARM_ALLOWED_REPOS` (spec 13); default is none. `SWARM_REPO_WORK` must be set to `1` for the job to do anything.
- At most one open swarm pull request at a time (branch prefix `swarm/`); while one is open the run exits with `skipped: pr open`. At most one pull request per run. There is no per-day limit (owner decision 2026-11-19, after confirming the subscription path uses no API credits); the one-open-PR rule is what bounds the output.
- Edits are limited to the task's `allowed_paths` and to `SWARM_MAX_FILES` (default 6) and `SWARM_MAX_LINES` (default 300) changed lines. Never editable regardless of the task: `.github/`, `ci/`, `deploy/secrets/`, `*.sops.yaml`, `.sops.yaml`, `CLAUDE.md`, `.specter/tasklist.md` markers other than checking off its own task, and the swarm's own code under `deploy/hermes/jobs/swarm*` and `deploy/hermes/jobs/claude-haiku`.
- A change that touches Kubernetes manifests, `deploy/istio/`, NetworkPolicies or egress config is allowed only if the task is also marked `[swarm-deploy]`; those pull requests are labelled `needs-careful-review`.
- Workers get no GitHub token, no kubectl and no shell. A script applies worker output (unified diffs from verifiers `diff_allowed`), runs the repo's tests, commits, pushes and opens the pull request. The token is the spec 11 fine-grained token, used only by those scripts and only through the Squid proxy to GitHub hosts. Fetched and repository text is untrusted and wrapped in delimiters (spec 13).
- The pull request is opened by the script, never merged by it: the job holds no merge call, and the token's Pull requests scope is used for create and comment only. A pull request that fails its checks is left open with a failure comment, never force-pushed over.

**Flow**
1. Preflight (`make swarm-preflight`), disabled flags, `hermes pause` check, allowlist, open-PR check, then `pick-task.py`.
2. Clone the repo into `/workspace`, branch `swarm/<date>-<task-slug>` from the default branch.
3. Plan with the orchestrator (spec 13), steps limited to the derived files. Each step edits exactly one listed file and returns its complete new content; scripts write it and check the resulting diff. Haiku handles `hard` steps and escalations, Qwen the bounded ones.
4. Verify with scripts only: diff inside `allowed_paths`, line and file caps, no forbidden path, `scripts/check-sops.sh` clean, and the repo's offline tests (`make test` where present, plus any command named in the task) exit 0. A failed step follows the spec 13 retry ladder, then the run ends `failed` and the branch is deleted.
5. Remove the task from `.specter/tasklist.md` in the same commit that completes it; open the pull request with the task text, files changed, the verifier results, Haiku call count and run ID, the label `swarm`, and no auto-merge.

**Observability and control**
- Audit, digest and metrics reuse spec 13 (`swarm_last_run_status` and the new `swarm_prs_opened_total`). Each run writes a digest line with the pull request URL or the skip or failure reason.
- Kill switches are the spec 13 ones plus `SWARM_REPO_WORK` unset. `make swarm-run TASK=repo-work` runs it on demand (dry-run builds the plan and the picked task without any worker call, clone push or pull request). The cron entry is registered paused.

## Acceptance Criteria

- [ ] `pick-task.py` tests: picks the first `[swarm]` unstarted task with a file list; skips unmarked, `[~]`, `[needs-owner]`, tasks under the excluded headings, and tasks without a file list; derives `allowed_paths` from the task text only.
- [ ] Guards are tested offline with a fake gateway, fake wrapper and fake GitHub API: repo not allowlisted, `SWARM_REPO_WORK` unset, an open `swarm/` pull request, and a forbidden path each end the run before any worker call or push.
- [ ] A diff touching a forbidden path, a path outside `allowed_paths`, or more than the file or line cap is rejected by the verifier and the branch is never pushed.
- [ ] The job has no merge code path: `git grep -nE 'merge' deploy/hermes/jobs/swarm-repo-work` finds no GitHub merge call, and the fake API records no merge request in any test.
- [ ] A forced failing test ends the run `failed`, deletes the local branch, pushes nothing and writes an audit entry and digest line.
- [ ] `make swarm-plan TASK=repo-work` on a fixture repo prints the picked task, the derived `allowed_paths` and a valid plan, and makes no worker call, push or pull request.
- [ ] Live, on the rehearsal repo `dsm0014/claude-specter-auto` first: one task is completed, the pull request is opened (labelled `swarm`, with the verifier summary and Haiku call count), nothing is merged, a second run reports `skipped: pr open`, and `hermes pause` stops a run.
- [ ] Live on this repository: one `[swarm]` task from the task list produces a pull request that passes `make test`; the owner merges it. The cron entry is registered paused.
- [ ] `git grep -E 'sk-ant-|ghp_|github_pat_' -- . ':!*.md'` is clean; the token never appears in a log, audit file, pull request body or ConfigMap.
- [ ] `deploy/hermes/README.md` documents the marker syntax, guards, forbidden paths, the Make targets and how to queue and unqueue a task; spec 13 and the task list point to this spec.
