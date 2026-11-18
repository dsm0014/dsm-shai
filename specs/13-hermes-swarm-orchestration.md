# Spec 13 — Hermes Swarm Orchestration (Haiku + Qwen 9B)

> **Amendment (spec 12 rewrite):** `haiku` is no longer a LiteLLM alias. Every Haiku call in this spec means `/opt/jobs/claude-haiku/claude-haiku.sh` (Claude Code CLI, subscription). Wherever this spec says Haiku goes through LiteLLM, uses the `hermes` key budget, or reports LiteLLM spend, read: the wrapper's call-count caps and `audit.jsonl` instead (tokens and USD are not metered on a subscription). "Revoke `haiku` on the key" becomes the wrapper's `disabled` flag or removing the token. Reconcile the criteria when implementing.

**Status:** TODO

## Purpose

Let Hermes finish tasks on its own by splitting them across a swarm of workers: Claude Haiku (via LiteLLM, spec 12) for planning, judging and hard steps, and local `qwen3.5:9b` for cheap, high-volume steps. A cron template and a working example job show how to schedule such tasks. Depends on specs 04 (Hermes), 09 (LiteLLM), 11 (nightly job patterns and guardrails) and 12 (`haiku` alias).

## Behavior

**Roles and routing**
- Orchestrator: `haiku`. It decomposes a task into at most 12 steps, each tagged with a worker class, and judges results. It never edits files or runs commands itself.
- Workers: `chat` (qwen3.5:9b) by default for bounded steps (summarise, extract, draft, classify, apply a known edit); `haiku` for steps tagged `hard` or after a local worker fails its verifier twice. Routing is by a deterministic script (`route.py`) from the tag and the retry count; a model never picks its own tier.
- A task may run with local workers only (`SWARM_ORCHESTRATOR=chat`) when Anthropic is unreachable or the Haiku budget is spent. This is chosen by configuration, never by an automatic fallback in LiteLLM (spec 12).

**Concurrency and VRAM**
- The GPU runs one chat model with `max_parallel_requests: 2` (spec 09), so the local pool is capped at 2 simultaneous workers. Haiku workers are capped at `SWARM_HAIKU_PARALLEL` (default 4). A scheduler script (`swarm.py`) owns the queue so a third local call is never sent and 429s are not used as flow control. Local and Haiku work run concurrently; local work never exceeds 2.
- Every worker call goes through LiteLLM with the `hermes` key. Each step is a separate `hermes -z` call (or direct LiteLLM request) with a versioned prompt file, context under 16K tokens and a required output schema, as in spec 11.

**Task plan and state**
- A task is a YAML file with `goal`, `allowed_paths`, `max_steps`, `max_haiku_tokens`, `timeout_minutes`, `verifiers`. The orchestrator writes a plan JSON (steps, dependencies, worker class), validated against a schema before any worker starts. An invalid plan is retried once, then the task fails.
- State lives under `/opt/data/swarm/runs/<run-id>/` (plan, per-step input and output, verifier results). Steps with no dependency between them run in parallel within the caps above; a step starts only when its dependencies passed their verifiers.
- Fetched and generated content is untrusted: prompts wrap it in delimiters, and worker output is only accepted through the verifier and the path allowlist.

**Verification and autonomy limits**
- Each step has a non-LLM verifier (schema parses, file exists, diff within `allowed_paths` and line caps, tests exit 0). Only verifier results count as success. A failed step retries once on the same tier, once on the next tier (`chat` then `haiku`), then fails the task and discards uncommitted work.
- Hard caps, enforced by scripts and by the LiteLLM key budget: steps per task, Haiku tokens per task and per day, wall-clock timeout (`timeout`), at most one running swarm per task name (`flock`). Reaching any cap ends the task with status `capped` and a digest line, never a retry loop.
- Workers have no new credentials: no kubectl, no GitHub token unless the task file lists it, no write outside `allowed_paths`. Egress is unchanged from spec 11 (GitHub hosts only, through the proxy); Anthropic is reached only through LiteLLM.
- Audit: append-only JSONL `/opt/data/swarm/audit.jsonl` with run ID, task, per-step worker, tier, verifier result, token usage and cost per model (from LiteLLM spend for key `hermes`), plus a one-line summary `remember` into OpenViking. Metrics `swarm_last_success_timestamp`, `swarm_last_run_status` and `swarm_haiku_tokens_total` are served read-only and scraped by Prometheus (spec 06).
- Kill switches: `hermes pause`, a `/opt/data/swarm/disabled` flag file checked before each run, revoking the `haiku` permission on the `hermes` virtual key.

**Make interface (root `Makefile`, same style as the `nightly-*` targets; each target has a `##` help line)**
- `make swarm-preflight`: check the tools, state directory, `haiku` and `chat` reachability through LiteLLM, and that the key budget is not spent.
- `make swarm-plan TASK=<name>`: the dry run; builds and prints the plan, makes no worker call, spends nothing.
- `make swarm-run TASK=<name>`: runs the task in the pod in the background with a log under `/opt/data/swarm/`. `TASK` is a name under `deploy/hermes/jobs/` (default `swarm-example`) or a path to a task YAML. Tasks that write outside the state directory need `CONFIRM=1`, as `nightly-run` does. `SWARM_ORCHESTRATOR=chat` and `SWARM_HAIKU_PARALLEL=<n>` pass through as variables.
- `make swarm-status`: running or not, last audit entries, digest lines, metrics, and Haiku spend for the day.
- `make swarm-stop`: stops the running swarm cleanly (releases the lock); `make swarm-test`: the offline tests (fake gateway, no cluster needed). `make hermes-pause` stays the emergency stop.
- A missing or unknown `TASK` prints usage and exits 2; the targets work from the repo root with no extra setup.

**Hermes cron template and example**
- `deploy/hermes/jobs/swarm-template/` holds a documented template: `task.example.yaml`, `run.sh` (flock, timeout, state dir, calls `swarm.py`), `register-cron.sh` (prints the `hermes cron create ... --paused` command with a schedule placeholder, same convention as spec 11), and a README of every field.
- `deploy/hermes/jobs/swarm-example/` is a runnable instance of the template: a daily "repo digest" task (nightly or on demand) that reads a configured public repo, uses local workers to summarise each changed file, uses a Haiku step to merge the summaries into one report, and stores it in OpenViking. It writes no files outside its state directory, so it is safe to run unattended.
- Both are registered paused. A `--dry-run` mode builds and prints the plan, calls no worker and spends nothing.

## Acceptance Criteria

- [ ] `swarm.py --dry-run` on the example prints a schema-valid plan and makes no LiteLLM call (spend and token metrics unchanged).
- [ ] The scheduler never has more than 2 `chat` requests in flight and never more than `SWARM_HAIKU_PARALLEL` `haiku` requests (asserted by a test with a fake gateway); no 429 is produced in a full example run.
- [ ] `route.py` tests: a `hard` step goes to `haiku`; a normal step goes to `chat`; after two local verifier failures it goes to `haiku`; the model output cannot change the tier.
- [ ] A forced verifier failure ends the task `failed`, discards uncommitted work, writes an audit entry and a digest line, and sets `swarm_last_run_status` to failure.
- [ ] Reaching `max_haiku_tokens`, `max_steps` or the timeout ends the task `capped` with no further calls; the `hermes` key budget rejects `haiku` calls once spent while `chat` keeps working.
- [ ] A second launch of the same task logs `skipped: locked`; `hermes pause`, the disabled flag and revoking `haiku` on the key each stop a run (the flag is tested locally).
- [ ] With `SWARM_ORCHESTRATOR=chat` and Anthropic blocked, the example completes with local workers only and the audit entry records `haiku_tokens: 0`.
- [ ] A live run of `swarm-example` completes: local steps run, one Haiku merge step runs, the report is stored in OpenViking, the audit entry has per-model token counts matching LiteLLM spend, and nothing is written outside `/opt/data/swarm/`.
- [ ] The cron entry registers paused via `register-cron.sh`; `hermes cron resume <id>` runs it at the next schedule time; `hermes cron incidents` shows a failure when forced.
- [ ] `make swarm-test` passes offline; `make swarm-plan`, `swarm-run`, `swarm-status` and `swarm-stop` work on `swarm-example` from the repo root; a missing `TASK` exits 2 with usage; `make help` lists every swarm target.
- [ ] `git grep -E 'sk-ant-|ghp_|github_pat_' -- . ':!*.md'` is clean; no key appears in a ConfigMap, log or audit file.
- [ ] `deploy/hermes/README.md` documents the roles, caps, routing rules, template fields, kill switches and how to create a new job from the template; spec 04 carries a pointer to this spec.
