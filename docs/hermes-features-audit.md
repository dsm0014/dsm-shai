# Hermes features audit: custom jobs versus Hermes Agent

**As of 2026-11-20.** Audit only; no job code changed. Scope: the custom jobs under `deploy/hermes/jobs/` (swarm, repo-maintainer, nightly-specter, claude-haiku, plus the swarm-example, swarm-repo-work and swarm-template wrappers).

## Method

- Live pod (read-only): Hermes Agent v0.23.1 (image `dsm-shai/hermes`); `hermes cron list`; `/opt/data/config.yaml`; `/opt/data/SOUL.md`; `/opt/data/hooks` (empty); `/opt/data/scripts`; the bundled skills under `/opt/data/skills`; `hermes kanban --help` and `hermes kanban swarm --help`; `hermes cron create --help`; `hermes pause --help`; the `hermes` container's environment (variable names and secret sources only, no values).
- Hermes source in `/opt/hermes`: `cron/AGENTS.md`, `tools/environments/local.py` (`build_subprocess_env`, secret scrubbing), `tools/delegate_tool_config.py`, `hermes_cli/subcommands/pause.py` and `agent/estop.py`, `hermes_cli/config_defaults.py`.
- Custom code read in this repository (file paths below).

## Findings that frame the verdicts

1. **Hermes cron cannot carry `GITHUB_TOKEN`.** The cron script environment goes through `build_subprocess_env` with secret scrubbing; GitHub secrets never pass through. The swarm-repo-work and nightly-specter entries are paused for this reason. The repo-maintainer already runs as a Kubernetes CronJob for it.
2. **`hermes kanban swarm` exists** (worker, verifier and synthesizer cards on a shared board). It is the closest Hermes feature to the swarm, but it does not route by script, enforce tier caps, or run non-LLM verifiers.
3. **`delegate_task` allows up to 10 concurrent children by default** (`delegation.max_concurrent_children`). Children inherit parent toolsets and the model chooses how to use them. Spec 13 needs the script, not the model, to choose the tier.
4. **`hermes pause` writes the same ESTOP sentinel** (`$HERMES_HOME/ESTOP`) that `swarm.py` and `maintain.py` check. The jobs check the file themselves because CronJob and manual runs are not Hermes cron.
5. **No hooks, no `quick_commands`, no chat delivery target are configured.** `/opt/data/hooks` is empty, `quick_commands` is `{}`, and Discord (spec 15) is not built.
6. **`gh` is not installed in the pod** (`which gh` returns nothing). The `github` and `requesting-code-review` skills assume the `gh` CLI and model judgement; the jobs use REST with script gates.
7. **The `hermes` container has `GITHUB_TOKEN`** from secret `hermes-github` (the nightly specter's optional token), and a git credential helper reads it. Hermes's child-process scrubbing is what keeps it out of agent subprocesses per the source; this was not checked live from the agent's terminal.

## Audit table

Verdict `keep` means the custom code stays. `replace` means a Hermes feature takes over with the same behaviour, listed in the follow-up task item.

| # | Capability | Custom code location | Hermes equivalent | Verdict | Reason |
|---|---|---|---|---|---|
| 1 | Recurring run for jobs that need `GITHUB_TOKEN` (swarm-repo-work, nightly-specter) | `deploy/hermes/jobs/swarm-repo-work/register-cron.sh`, `deploy/hermes/jobs/nightly-specter/register-cron.sh` | `hermes cron create --script --no-agent` | keep | Hermes cron strips GitHub secrets from script environments (finding 1). Move to CronJobs, as the maintainer did. |
| 2 | Recurring run for the token-free example job (swarm-example) | `deploy/hermes/jobs/swarm-example/register-cron.sh`, `deploy/hermes/jobs/swarm-template/register-cron.sh` | `hermes cron create --script --no-agent --paused` (live entry `21b81355887d`) | replace | Hermes cron already runs the job. The register scripts only print or write the same command plus a wrapper. Document the direct command instead; behaviour is unchanged. |
| 3 | Wrapper files for `--script` | `/opt/data/scripts/swarm-example.sh`, `swarm-repo-work.sh`, `repo-maintainer.sh` (written by the register scripts) | `--script` accepts only files under `HERMES_HOME/scripts` | keep | Required shim by Hermes design; each is one `exec` line. |
| 4 | Repo maintainer schedule | `deploy/hermes/maintainer-cronjob.yaml` | Hermes cron | keep | Token (finding 1); the CronJob also carries its own pod environment and ServiceAccount. |
| 5 | Parallel fan-out of model calls (workers, reviews) | `deploy/hermes/jobs/swarm/swarm.py`, `swarm/workers.py` | `delegate_task`; `hermes kanban swarm` | keep | Script-owned tier routing (`route.py`), per-tier parallel limits (2 local, `SWARM_HAIKU_PARALLEL`), hard caps and script verifiers (finding 2 and 3). Hermes children choose their own tools and have no such caps. |
| 6 | Local model call for bounded steps | `deploy/hermes/jobs/swarm/workers.py` (`call_chat`, direct POST to LiteLLM) | `hermes -z` one-shot (already used by `nightly-specter/orchestrate.py`) | keep | `hermes -z` adds the Hermes system prompt and tool schemas. The swarm needs a bare completion with `max_tokens` and `response_format`. Behaviour would change. Note the two jobs call the local model differently; that is not a reason to change either. |
| 7 | Haiku calls | `deploy/hermes/jobs/claude-haiku/claude-haiku.sh` | None: Hermes Claude providers use API keys | keep | Spec 12: subscription CLI, no API key, no tools, daily cap, parallel slots, audit without content. |
| 8 | Verification of step output | `deploy/hermes/jobs/swarm/verifiers.py` | `requesting-code-review` skill | keep | Spec 13 requires non-LLM verifiers to decide success. The skill is a model-judged workflow and needs `gh` (not installed). |
| 9 | PR review and merge gates | `deploy/hermes/jobs/repo-maintainer/maintain.py` (`gates`), `repo-maintainer/prompts/review.v1.txt` | `github` skill (`gh` CLI); `requesting-code-review` | keep | Gates are scripts; Haiku's verdict is one input with a veto. The skill needs `gh` and the token (finding 6). |
| 10 | GitHub REST access (open PR, merge, comment, labels) | `swarm/repo_work.py`, `repo-maintainer/maintain.py` (`api`), `nightly-specter/gh_api.py` | `github` skill (`gh` CLI) | keep | `gh` is absent; the token must reach the job environment (finding 1). Three REST helpers exist; sharing one is a code change, not a Hermes replacement. |
| 11 | Task selection from the queue | `deploy/hermes/jobs/swarm/pick_task.py` | `hermes kanban` board | keep | The source of truth is `.specter/tasklist.md` in git. A kanban board would be a second queue that can drift from git. |
| 12 | Prompts for each step | `deploy/hermes/jobs/*/prompts/*.v1.txt` | `SOUL.md` (agent persona, `/opt/data/SOUL.md`) | keep | SOUL.md is the persona for agent turns. The step prompts are versioned per job and per call, not persona. |
| 13 | State across runs (attempt counts, verdict cache, audit) | `attempts.json`, `verdicts.json`, `audit.jsonl` under `/opt/data/{swarm,maintainer,nightly-specter}` | OpenViking MCP toolset (`find`, `remember`, `read`, `list`) in `config.yaml` | keep | These are deterministic counters, cache keys and audit records that scripts read to gate work. Model-driven recall would let memory influence gates. |
| 14 | Kill switches | ESTOP checks in `swarm/swarm.py` and `repo-maintainer/maintain.py`; `disabled` flag files; `MAINT_MODE=off` | `hermes pause` (writes the same ESTOP file); shell hooks | keep | The make target already calls `hermes pause`. The jobs must check the sentinel themselves because CronJob and manual runs are not Hermes cron. Shell hooks run around agent tool calls, not around these scripts. |
| 15 | Operator commands | `Makefile` targets (`swarm-*`, `maint-*`, `hermes-pause`) | `quick_commands` in `config.yaml` (none configured) | keep | Operators run from the host through `kubectl exec`. `quick_commands` exists only inside Hermes chat surfaces, and Discord (spec 15) is not built. |
| 16 | Digest and status output | `lib.digest` writes `digest.log`; `metrics.prom` | Cron delivery of script stdout to a platform (`deliver`; currently `local`) | replace | Hermes delivers script stdout natively, and `digest.log` duplicates it only for `make swarm-status` and `maint-status`. Replace once a chat target exists. Keep `audit.jsonl` and `metrics.prom`. |

## Verdict summary

- **Replace (2):** rows 2 and 16.
- **Keep (14):** rows 1, 3 to 15. The main known reasons hold: GitHub token handling (rows 1, 4, 9, 10), script-only verifiers (rows 5, 8, 9), and hard caps (rows 5, 7).

## Follow-up work

The replace verdicts are the follow-up task item in `.specter/tasklist.md`, section 0 (`[needs-owner]`). Row 16 needs Discord (spec 15) first.

## Open points for the owner

- The `hermes` container's environment carries `GITHUB_TOKEN` (finding 7). The README says the agent's terminal never sees the maintainer token; that is a separate pod. Confirm from an agent terminal that the token is scrubbed before relying on it.
- The swarm (`workers.py`) and the nightly specter (`orchestrate.py`) call the local model in different ways (row 6). Pick one convention when either job is next changed.
