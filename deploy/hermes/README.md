# deploy/hermes

Hermes Agent (spec 04), namespace `hermes`. Status: **running headless, non-root, with a working end-to-end task and OpenViking memory**. Open items at the end.

## Image

`docker.io/nousresearch/hermes-agent:v0.23.1@sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08`

Deviation from spec 04: the spec asks for a build from `deploy/hermes/`. This cluster has no container build daemon (no Docker daemon, no root for `k3s ctr`). The upstream project publishes this image on each release, so it is pinned by digest. Bump the tag and digest together.

## Pod

- Runs as `hermes` (UID 10000) with `runAsNonRoot`, `RuntimeDefault` seccomp, no privilege escalation, all capabilities dropped. The upstream s6 init (root PID 1) is bypassed: the command is `/opt/hermes/docker/main-wrapper.sh gateway run`. An init container has already set ownership and seeded config.
- Headless: the long-lived foreground gateway. `hermes -z "..."` (one-shot) and `hermes chat` both use it.
- `/opt/data` (`HERMES_HOME`) is PVC `hermes-home` (10Gi, `local-path`, WSL ext4). Persistence verified across a pod replacement. The image uses `/opt/data`, not `~/.hermes`.
- `/workspace` is an `emptyDir` with `sizeLimit: 10Gi`.
- ServiceAccount `hermes`, `automountServiceAccountToken: false`. No token directory in the pod. No RBAC.
- No `hostPath`, no Docker or containerd socket. Requests 500m/2Gi, limits 2/4Gi.

## Config (`config.yaml`, ConfigMap `hermes-config`)

Copied to `/opt/data/config.yaml` by the init container on every start. The ConfigMap is the source of truth.

- `model`: `provider: custom`, `base_url: http://litellm.litellm.svc:4000/v1`, `default: chat`, `context_length: 65536` (must equal `OLLAMA_CONTEXT_LENGTH`; Hermes's floor is 64K), `key_env: LITELLM_HERMES_KEY`.
- `agent.reasoning_effort: none`: `llama3.1:8b` has no thinking mode, and Ollama rejects a `think` parameter.
- `agent.disabled_toolsets: [memory, web, browser]`: OpenViking is the only memory backend; `browser` is off because no browser backend is deployed. `terminal.cwd: /workspace` because the image cwd `/opt/hermes` is read-only. `web` is off because its search and scrape backends are cloud APIs (Parallel, Firecrawl) that need API keys and are refused by the egress proxy; Hermes reads GitHub with `terminal` (`curl`, `git`) through the proxy instead.
- `mcp_servers.openviking`: `http://openviking.openviking.svc:1933/mcp`, header `X-API-Key: ${OPENVIKING_KEY}` (tenant key for account `hermes`).

Secrets (SOPS, `deploy/secrets/hermes.sops.yaml`): `litellm-key` (virtual key `hermes`, allowlist `chat`, budget 20, 60 rpm) and `openviking-key` (tenant user key). Both enter the pod as env vars.

## Verification (done, 2026-11-16)

| Check | Result |
|---|---|
| One-shot prompt through LiteLLM to `chat` (`llama3.1:8b`) | `PONG` |
| End-to-end task with explicit terminal instruction: list the 3 largest files in `/workspace/data`, write `/workspace/largest.txt` | file written with `huge.bin`, `big.bin`, `mid.bin` (correct) |
| Memory write: `mcp__openviking__remember` with a two-message submission | extracted into `viking://user/hermes/memories/profile.md` |
| Same memory checked from outside the Hermes pod (OpenViking search with the tenant key) | found |
| Fresh Hermes process recalls the stored code via `mcp__openviking__search` | recalled (the abstract of `profile.md` contains the fact) |
| Pod replacement keeps `/opt/data` | file preserved |
| No cluster credentials in the pod | no token directory |

## Limits (llama3.1:8b, observed)

- **Planning and tool use need explicit instructions.** Without an explicit tool instruction, the model stopped after one call and claimed the file was written; the file did not exist. With "you must use the terminal tool; run exactly this command", it worked.
- **Tool-argument JSON is sometimes malformed** (`tool_call 'calls' is not valid JSON`). Hermes returns the error to the model, which usually retries. The `remember` call needed an exact-argument prompt. A multi-step `read` after `search` did not complete reliably. Recall worked when the search result itself held the fact.
- **Memory extraction needs substance.** A one-line `remember` extracted 0 memories (the extraction model is the VLM alias). A two-message submission extracted 1.

## Tool-use investigation (2026-11-16)

Controlled tests with `llama3.1:8b` (and `mistral-nemo:12b` as a candidate, removed afterwards):

- A single tool call, a multi-step answer after a tool result, 40 distractor tools, and a 10k-token system prompt: all 5/5 for llama. Streamed tool calls through LiteLLM: 5/5. So the model, gateway and streaming work in isolation.
- Hermes sends about 10.7k input tokens per call, and its tools go through Tool Search by default. In Hermes, the bridge calls (`tool_call` wrappers) failed with malformed JSON.
- With Tool Search off and the OpenViking tools limited to `find`, `remember`, `read` and `list` (`mcp_servers.openviking.tools.include`):
  - `read` by URI recalled the stored code 3/3, with no tool errors.
  - `search` failed because the model added a `detail` argument that OpenViking rejects (`detail` requires `mode='context'`).
  - `find` runs, but returns directory abstracts, so it does not surface `profile.md`.
  - An explicit shell task (`ls -S ... > file`) ran through the terminal tool and reported success, but produced no file in 1 of 2 runs. The model did not run the command it was given.

Conclusion (superseded by the next section): the earlier read was that the model could not follow multi-step instructions. The follow-up investigation found specific causes, so read "Why Hermes failed" before relying on this one. Hermes is still **not** reliably autonomous on `llama3.1:8b`.

## Why Hermes failed (investigation, 2026-11-16)

Method: capture the real request Hermes sends (`scripts/hermes-capture-proxy.py`), then replay it against any model with `scripts/bench-hermes-tools.py` (8 cases x 5 runs: three plain questions that need no tool, four single tool calls, one two-step task). The request is about 14k tokens: the 7.8k-character system prompt plus 29 tool schemas (about 53k characters). Hermes sends no `temperature`.

| Variant | Plain questions (15) | Tool calls (20) | Two-step (5) | Total (40) |
|---|---|---|---|---|
| `llama3.1:8b`, as Hermes runs it | 0 (called a tool every time) | 19 | 2 | 21 |
| same, `temperature 0.2` | 0 | 20 | 0 | 20 |
| same, only 10 tools | 0 | 19 | 0 | 19 |
| `llama3.1:8b` weights, corrected template | 15 | 0 (answered in prose and invented the results) | 5 | 20 |
| `qwen3:14b`, `reasoning_effort: none` | 15 | 20 | 5 | **40** |

Findings:

1. **The `llama3.1` Ollama template forces a tool call.** With tools present it rewrites the last user message to "respond with a JSON for a function call ... Question: ..." (`ollama show llama3.1:8b --template`). A plain question therefore gets a call to a tool that does not exist (`write`, `text`) or a wrong one (`text_to_speech` for "reply PONG"), and Ollama returns the invented call as message text. Temperature and tool count do not change this.
2. **Removing the forcing does not fix the model.** With the system-turn template, the same weights stop calling tools and make up the output (a file listing, file contents). The model cannot judge when a tool is needed. This is a model-quality limit, not only a template one.
3. **The model matters a lot.** `qwen3:14b` passed 40 of 40 on the same replay. It cannot be used because its native context is 40960 and Hermes requires 64,000 (see `deploy/ollama/README.md`). The next step is a model with a native context of at least 64K; candidates and results are recorded below.
4. **The coding persona was a test artifact.** On a CLI surface in a directory that looks like a code project, Hermes injects "You are a coding agent ... make changes through the tools, not the chat". `kubectl exec ... hermes -z` starts in `/opt/hermes`, which has a `pyproject.toml`, so the earlier README tests ran with that persona. `agent.coding_context: "off"` (now set in `config.yaml`) removes it, verified by capturing the request. The persona explained one failure ("reply PONG" calling the terminal); it did not explain the rest.
5. **Hermes tunes its prompt by model name, and ours is `chat`.** `TOOL_USE_ENFORCEMENT_MODELS` and the execution-guidance list (`agent/prompt_builder.py`) match substrings such as `qwen`, `gpt`, `gemma`, `mistral`. The LiteLLM alias `chat` matches none, so no model-specific guidance is applied. Not yet tested whether naming the alias after the model changes behaviour.
6. **Not the cause:** sampling (tested), tool count (tested), the LiteLLM and mesh path (a direct Ollama replay shows the same results), Tool Search (already off).

### Candidates (native context of at least 64K, fits 16 GiB)

`qwen3.5:9b` (256K, vision, tools), `gemma4:12b` (256K), `ministral-3:8b` (256K), `gpt-oss:20b` (128K, about 14 GB, little VRAM left at 64K). `gemma4:12b` and `ministral-3:8b` are downloaded but not yet benchmarked.

**`qwen3.5:9b`** (Ollama 0.40.16, same 8-case replay, 5 runs each):

| `reasoning_effort` sent | Plain (15) | Tool calls (20) | Two-step (5) | Total (40) |
|---|---|---|---|---|
| `none` (what `config.yaml` sends today) | 15 | 15 (5 failures) | 5 | 37 |
| not sent (thinking on, the model default) | 15 | 20 | 5 | **40** |
| `medium` | 15 | 19 | 5 | 39 |

- **Thinking must stay on.** With `reasoning_effort: none`, Ollama returned HTTP 500 (`XML syntax error ... element <function> closed by </parameter>`) on 4 to 6 of every 10 `read_file` calls: the model writes tool calls as XML, and Ollama's `qwen3.5` parser rejects a malformed one instead of returning it. Qwen's recommended sampling (`temperature 0.7, top_p 0.8, presence_penalty 1.5`) cut that to 2 of 10 but did not remove it. With thinking on, `read_file` succeeded 10 of 10. If this model is adopted, change `agent.reasoning_effort` away from `"none"`.
- **It fits.** Loaded at `num_ctx 65536` it uses 6.43 GiB (hybrid attention keeps the cache small), 0.31 GiB more for the embedding model; the device was at 9.7 of 16 GiB, about 6.6 GiB free. Native context is 262144, so the 64K floor is not a constraint.
- **Not yet tested:** real Hermes tasks through LiteLLM with this model (the replay sends Hermes's real request straight to Ollama, so it skips LiteLLM and Hermes's own loop), long multi-step tasks, and the memory-recall flow. Adopting it needs a change to `deploy/litellm/config.yaml` (`chat` alias), the model preload job, and the `reasoning_effort` above.

### After a restart

If Hermes replies with nothing or "waiting for the provider to recover", check mesh enrolment first (`deploy/istio/README.md`, "Restart recovery"). A `rollout restart` of `hermes` is reverted by Flux, so delete the pod.

## Nightly specter job (spec 11)

A nightly job that evaluates the owner's `claude-specter` repository against open-source equivalents on GitHub, then either writes improvement specs (Mode A) or implements one (Mode B), opens a pull request and merges it when the guardrails pass. **It is built but inert:** `NIGHTLY_REPO` is empty, there is no token, and the cron entry is not registered. Until both exist, `run.sh` exits 0 with the audit line `not configured`.

| Part | Where |
|---|---|
| Scripts and prompts (source) | `deploy/hermes/jobs/nightly-specter/` |
| In the pod (read-only ConfigMap `hermes-nightly-specter`) | `/opt/jobs/nightly-specter/` |
| State: lock, `runs/<date>.json`, `audit.jsonl`, `digest.log`, `metrics.prom` | `/opt/data/nightly-specter/` (PVC) |
| Clone and scratch | `/workspace/claude-specter`, `/tmp` (lost on restart; an interrupted run is abandoned) |
| Settings (ConfigMap `nightly-specter-env`) | `NIGHTLY_ALLOWED_REPOS` (isolation guard: the job refuses any `NIGHTLY_REPO` not listed, in `run.sh` and `gh_api.repo()`; add the real repo here at go-live), `NIGHTLY_REPO` (owner/name; `dsm0014/claude-specter-auto`, the private rehearsal copy, until the real repo is switched in), `IMPL_PROBATION_NIGHTS=1`, caps 400 lines / 12 files, 5 repos, 3 specs, 90 min wall clock |
| Token | Secret `hermes-github`, key `token`, env `GITHUB_TOKEN` (optional) |
| Egress | `deploy/istio/egress/` (Squid: restricted listener `:3128` for GitHub, Anthropic and Discord; research listener `:3129`, Haiku only) |
| Metrics and alerts | sidecar on 9101, `deploy/monitoring/extras/nightly-alerts.yaml` |

**How a run works.** `run.sh` takes a `flock`, checks the configuration and the kill switches, then `orchestrate.py` clones the repo and `select_mode.py` picks the mode (the model never does). Every model call is one `hermes -z` with a versioned prompt and is followed by a script verifier; a step gets two attempts. `guard.py` checks the diff (paths, size, secrets, spec structure) before anything is pushed. The model's own claim of success is not used.

**Tests (offline, no cluster, no network, no model):** `sh deploy/hermes/jobs/nightly-specter/tests/run_tests.sh` runs 36 tests with a stub GitHub API, a stub `hermes` and fixture repos.

### Going live (the owner's steps)

1. Create a fine-grained token (or a GitHub App installation token) for all repositories: Contents read/write, Pull requests read/write, Metadata read. No Administration, no Workflows. The current token expires 2027-02-14. Because the token reaches every repository, the isolation guard (`NIGHTLY_ALLOWED_REPOS` for the nightly job, `SWARM_ALLOWED_REPOS` for the swarm) is what limits where the jobs may write.
2. Encrypt it. Write a `Secret` named `hermes-github` in namespace `hermes` with `stringData.token`, then `sops --encrypt --filename-override deploy/secrets/hermes-github.sops.yaml <file> > deploy/secrets/hermes-github.sops.yaml`, delete the plaintext file, add the new file to `deploy/secrets/kustomization.yaml`, run `bash scripts/check-sops.sh`, commit. Never commit the plaintext.
3. Set `NIGHTLY_REPO=owner/name` in `deploy/hermes/kustomization.yaml` (`nightly-specter-env`). Point it at a **throwaway fork** first.
4. After the merge reconciles, delete the hermes pod (a `rollout restart` is reverted by Flux) and check the pod is Ready.
5. Verify in the pod: `kubectl -n hermes exec deploy/hermes -c hermes -- bash /opt/jobs/nightly-specter/run.sh --preflight` (checks python3, git, flock, curl, timeout, hermes and the state directory; installs nothing). On 2026-11-16 the image had git, curl, flock, timeout and Python 3.14, and no `gh` or `jq` (the job uses the REST API).
6. Verify the proxy (see `deploy/istio/egress/README.md`, "Verify before use"), then run `bash /opt/jobs/nightly-specter/run.sh --dry-run` and read `audit.jsonl`.
7. Rehearse on the fork: a dry run, a Mode A run (up to 3 specs), then a Mode B run, the forced-failure case, `hermes pause`, and the one-PR-per-night case.
8. Register the cron entry **paused**: `sh /opt/jobs/nightly-specter/register-cron.sh` prints the `hermes cron create` command (`--script ... --no-agent --paused`). Check that `--script` accepts a path outside `HERMES_HOME`; if not, copy `run.sh` into the directory Hermes expects. Resume with `hermes cron resume <id>` only after the rehearsal. Point `NIGHTLY_REPO` at the real repository last.

### Human override

Merges are **unattended**: no one reads a diff before it reaches `main` of the target repository. Spec-only pull requests merge from night 1; implementation pull requests merge only after `IMPL_PROBATION_NIGHTS` clean nights in a row (default **1**, the owner's choice so that work keeps progressing if a PR is not reviewed within a day; `0` merges from the first night). In practice the first real Mode A run is the clean night, so later implementation PRs merge on their own. After a failed run or a revert the count is 0 again: the next implementation PR stays open for review and the following night reports `HOLD` until it is merged or closed. The owner can stop or undo it at any point:

- **Stop now:** `hermes pause` (halts cron dispatch and new gateway turns; `hermes resume` lifts it), or `touch /opt/data/nightly-specter/disabled` in the pod, or commit a `.nightly-disabled` file to the target repo's default branch.
- **Force review:** turn on required reviews in branch protection on the target repo; the merge call then fails and the PR stays open (the next night reports HOLD).
- **Revert a merge:** `git revert -m 1 <merge-sha>` on the target repo, then `python3 /opt/jobs/nightly-specter/lib.py record-revert "<reason>"` in the pod so the clean-night count resets.
- **Revoke access:** delete the token in GitHub. The job then fails closed, writes `FAILED` to `digest.log` and the alerts fire.
- **Rotate:** create the new token, edit the SOPS file, commit, let Flux reconcile, delete the hermes pod, run `--dry-run`, then revoke the old token.

### Alerts

There is no Alertmanager. `digest.log` (one line per run) is the primary signal; the metrics (`nightly_specter_last_success_timestamp`, `nightly_specter_last_run_status`, `nightly_specter_consecutive_failures`) feed Prometheus rules `NightlySpecterStale`, `NightlySpecterLastRunFailed` and `NightlySpecterRepeatedFailures`. `hermes cron incidents` also lists failed cron runs once the entry exists.

### Known limits

The 9B model is the weak link: specs and code it writes are lower quality than Claude Code's, which is why every step is verified by a script and why implementation merges wait for one clean run (and after any failure, for review). `claude-specter`'s own skills do not run in Hermes; the job gives the model their markdown procedure as prompt text. Fetched repository text is untrusted and is wrapped in markers, but a prompt-injection that stays inside the allowed paths would still pass the guard, so read the pull requests.

## Tool Search and alias naming (replay benchmark, 2026-11-16)

Captured one real Hermes request per variant and replayed it against `qwen3.5:9b` (thinking on, 8 cases x 5 runs, `scripts/bench-hermes-tools.py`):

| Variant | Tools sent | Result | Notes |
|---|---|---|---|
| Current: alias `chat`, Tool Search off | 29 | 38/40 | `remember` 3/5 (no call, prose) |
| Model name `qwen3.5:9b` | 29 | 40/40 | Hermes adds about 4.8K characters of tool-use enforcement text for model names it recognises |
| Tool Search on | 19 | 33/40 | `remember` 0/5, `ls` 3/5; fewer tokens (about 18K characters less) but worse |

Tool Search stays off. Naming the model instead of the alias scored 2 cases higher in one run of 5 (not significant) and changes the system prompt, so it is a candidate to test with a real multi-step task before changing `config.yaml`; it also needs the LiteLLM key allowlist to permit the new name. `gemma4:12b` and `ministral-3:8b` are no longer on the PVC and were not benchmarked.

## Open items (spec 04)

- **Browser MCP tools** (spec 04 and spec 09 `deploy/browser/`): not deployed. Only `hermes` gets browser tools.
- **LiteLLM MCP gateway**: Hermes connects to OpenViking's MCP endpoint directly, not through the gateway. Register it with LiteLLM when the gateway's MCP support is set up.
- **Egress and network policy** (spec 04 and spec 08 part B): default-deny by NetworkPolicy; the only added route is the GitHub proxy for the nightly job (spec 11). The hostname allowlist for anything else is not planned.
- **`readOnlyRootFilesystem`**: on (tested 2026-11-16). The gateway starts, reconnects to OpenViking and answers a chat with only `/opt/data` (PVC), `/workspace` and an `emptyDir` on `/tmp` writable. Writing under `/opt/hermes` fails with "Read-only file system" as intended.
- **Flux**: the `hermes` stage is in `clusters/dsm-shai/` and reconciles from `main`. The `hermes-egress` NetworkPolicy is now part of it (it was applied by hand before spec 11).

## Operation

```sh
kubectl -n hermes logs deploy/hermes -c hermes --tail=100                       # gateway log
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes doctor'                    # config check
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes -z "..."'                  # one-shot prompt
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes logs | grep tool'          # tool activity
```

## Swarm orchestration (spec 13)

Haiku plans and merges, local `qwen3.5:9b` (alias `chat`) does the bounded steps, and scripts own routing, caps and verification. Engine: `deploy/hermes/jobs/swarm/` (mounted at `/opt/jobs/swarm`); example job `swarm-example` (daily repo digest); template `swarm-template`. State: `/opt/data/swarm/` (`audit.jsonl`, `digest.log`, `metrics.prom`, `runs/<id>/`, `locks/`).

| Role | Who | Notes |
|---|---|---|
| Orchestrator | Haiku through `claude-haiku.sh` (`SWARM_ORCHESTRATOR=chat` makes it local) | Writes a plan of at most 12 steps; never edits files or runs commands |
| Worker `normal` | `chat` through LiteLLM (`hermes` key) | At most 2 in flight (LiteLLM `max_parallel_requests: 2`); the scheduler queues, 429s are never used as flow control |
| Worker `hard` or escalated | Haiku wrapper | At most `SWARM_HAIKU_PARALLEL` (default 2, must not exceed the wrapper's `CLAUDE_HAIKU_PARALLEL`) |

**Routing** (`route.py`, no model input): `hard` goes to Haiku; `normal` goes to `chat`; after two local verifier failures a step goes to Haiku; with `SWARM_ORCHESTRATOR=chat` everything stays local. **Retry ladder:** same tier once, next tier once, then the task fails and uncommitted work is discarded. Only a non-LLM verifier result counts as success.

**Caps** (any of them ends the run `capped`, never a retry loop): `max_steps`, `max_haiku_calls` (every wrapper call counts), `timeout_minutes`, the wrapper's daily cap (`CLAUDE_HAIKU_DAILY_CALLS`, shared with every Haiku caller), one run per task name (`skipped: locked`). Haiku tokens and cost are not metered on a subscription; the audit records calls and bytes (local token counts come from the LiteLLM `usage` field).

**Fail closed:** a task's `repo` must be in `SWARM_ALLOWED_REPOS` (ConfigMap `swarm-env`, currently `dsm0014/dsm-shai`); anything else, or an empty list, is refused with exit 2 before any call. Fetched content is wrapped in `UNTRUSTED_CONTENT` markers.

**Local chat budget:** `SWARM_CHAT_MAX_TOKENS` (default 8000) caps each local call's output; the model thinks first, so a small cap can leave the reply empty.

**Kill switches:** `make hermes-pause` (the `ESTOP` file), `touch /opt/data/swarm/disabled`, `touch /opt/data/claude-haiku/disabled` (stops every Haiku call; the run ends `capped`), `make swarm-stop`.

**Task file** (restricted YAML: `key: value`, block lists, one nested map, JSON values):

| Field | Meaning |
|---|---|
| `name`, `goal` | Required. The goal is what the orchestrator plans against |
| `repo` | Target repo, checked against `SWARM_ALLOWED_REPOS` |
| `source` | `{type: github_changes, commits, max_items}`: changed files of the latest commits become the inputs (public repo, unauthenticated, through the proxy) |
| `allowed_paths` | Paths a diff-producing step may touch (`diff_allowed` verifier) |
| `max_steps`, `max_haiku_calls`, `timeout_minutes` | The caps above |
| `verifiers`, `min_chars`, `max_chars` | Extra verifiers for every step. Always on: `nonempty`, `no_secrets`, and `cites_inputs` for a step with inputs. Others: `json`, `diff_allowed` |

**Make targets:** `swarm-preflight`, `swarm-plan TASK=<name>` (dry run: a scripted plan, no model call, spends nothing; a live run asks the orchestrator), `swarm-run TASK=<name>` (background, log at `/opt/data/swarm/<name>.log`; `SWARM_ORCHESTRATOR=chat` and `SWARM_HAIKU_PARALLEL=n` pass through), `swarm-status`, `swarm-stop`, `swarm-test` (offline).

**New job from the template:** copy `deploy/hermes/jobs/swarm-template/` to `deploy/hermes/jobs/swarm-<name>/`, edit `task.yaml`, add its files to the `hermes-swarm` generator in `kustomization.yaml` and a volume and mount in `hermes.yaml` (same as `swarm-example`), add the repo to `SWARM_ALLOWED_REPOS`, test with `make swarm-plan TASK=swarm-<name>`, then `register-cron.sh <name>` (prints the paused `hermes cron create` command; `--apply` writes a wrapper into `/opt/data/scripts/`, which is the only place Hermes accepts a `--script` from, and runs it) and `hermes cron resume <id>` when ready.

## Repo maintainer (spec 16)

A Hermes job that does what the manual loop did: review the open swarm pull requests, merge the good ones, then start the next repo-work task. Job: `deploy/hermes/jobs/repo-maintainer/` (`maintain.py`, `repos.yaml`, `prompts/review.v1.txt`); it imports the swarm engine from `/opt/jobs/swarm`. **It never lets a model decide alone:** a merge needs every script gate **and** a `merge` verdict from Haiku.

**Configure the repositories:** `deploy/hermes/jobs/repo-maintainer/repos.yaml` has one section per repository (`mode`, `tasklist_path`, `branch_prefix`, `reviewer`, `max_merges_per_run` (default 1), `max_merges_per_day` (default 100; `MAINT_MAX_MERGES_PER_DAY` and `MAINT_MAX_MERGES_PER_RUN` in ConfigMap `maintainer-env` set the default for every repository), `max_attempts`, `merge_deploy`, `auto_queue`); `MAINT_REPOS` (comma list) adds repositories with the defaults. A repository runs only if it is in **both** `MAINT_ALLOWED_REPOS` (ConfigMap `maintainer-env`) and `SWARM_ALLOWED_REPOS` (`swarm-env`); an unset list means nothing runs, and `MAINT_MODE=off` stops everything. To add a repository: a reviewed PR that adds it to `repos.yaml` and both allowlists.

**Modes:** `observe` (the default: comments once per PR head, never merges or closes), `merge` (merges PRs that pass, closes failed ones), `merge-and-run` (also starts the next repo-work task when no swarm PR is open). Raise a mode only in a reviewed PR; a manual `make maint-run` against a repository that is not in `observe` needs `CONFIRM=1`.

**Candidates:** open PRs from branches starting with `branch_prefix` (default `swarm/`), opened by the token's own account, labelled `swarm`. **Gates (from the real diff and the API):** only the task's named files plus the task list; none of the forbidden paths; file and line caps; the task-list change removes exactly one unstarted `[swarm]` line; no verified `[x]` criterion becomes `[ ]`; no cut-down file (deletions far above additions); the head is not behind; the default branch's last check run is not red; the repository's test command passes in a fresh clone of the PR head; deploy-class paths need `[swarm-deploy]` and `merge_deploy: true`. Severe failures close the PR with a comment; the rest leave a comment and count an attempt, and after `max_attempts` the task is marked `[needs-owner]` through a PR. **Limits:** one merge per repository per run and 8 per day by default; the merge call refuses if the head moved since review.

**`auto_queue`** (off by default) opens a PR labelled `maintainer` that adds `[swarm]` to the first short task naming 1 to 3 existing files under the worker size cap. The maintainer never merges task-list edits it opens: you do.

**Run:** `make maint-preflight`, `make maint-plan` (every gate and verdict, no write), `make maint-run [REPO=owner/name] [CONFIRM=1]`, `make maint-status`, `make maint-stop`, `make maint-suspend` / `make maint-resume`, `make maint-test`. **Scheduling:** a Kubernetes CronJob `repo-maintainer` in namespace `hermes` (`deploy/hermes/maintainer-cronjob.yaml`, every 30 minutes, one pass at a time), **not** a Hermes cron entry: Hermes strips `GITHUB_TOKEN` and the other tier-1 secrets from cron script environments and refuses to pass them through (found 2026-11-20 as a 401), so the token lives in the CronJob pod's own environment and the agent's terminal never sees it. The pod carries the hermes labels and ServiceAccount, so the same NetworkPolicy and mesh policy apply, and it shares the `hermes-home` volume for state and kill switches. Kill switches: `make maint-suspend` (stops new passes), `make hermes-pause` (the `ESTOP` file), `/opt/data/maintainer/disabled`, `/opt/data/claude-haiku/disabled`, `MAINT_MODE=off`. **Undo a merge:** `maintain.py revert owner/name <pr>` opens a revert PR (never merges it). State: `/opt/data/maintainer/` (`audit.jsonl`, `digest.log`, `metrics.prom`, `attempts.json`, `verdicts.json`). Metrics `maintainer_last_success_timestamp`, `maintainer_last_run_status`, `maintainer_merges_total`, `maintainer_closed_total`.

**Branch protection:** for any repository where the job runs in `merge` mode, enable branch protection on the default branch (required status checks at least), so a merge by the token still has to pass CI.

## Autonomous repo work (spec 14)

The swarm can work through the target repo's task list and open pull requests. **It never merges.** Job: `deploy/hermes/jobs/swarm-repo-work/` (task `repo-work`); code: `pick_task.py` and `repo_work.py` next to the swarm engine.

**Queue a task:** in `.specter/tasklist.md` put `[swarm]` after the checkbox and name the files in backticks: `- [ ] [swarm] Add a make hermes-task example to `deploy/hermes/README.md``. Unqueue it by deleting the marker. Never picked: unmarked items, `[~]` started items, `[needs-owner]`, and anything under "Needs you at the machine", "Proposed, not decided" or "Not planned". Items with no file list are skipped with a digest line. `[swarm-deploy]` is required for manifests (`deploy/**/*.yaml`), mesh and egress config; those PRs get the `needs-careful-review` label.

**Guards (fail closed):** `SWARM_REPO_WORK=1` (ConfigMap `swarm-env`, default `0`), the repo in `SWARM_ALLOWED_REPOS`, no open PR from a `swarm/` branch (one at a time; there is no per-day limit), one PR per run, at most `SWARM_MAX_FILES` (6) files and `SWARM_MAX_LINES` (300) changed lines, a file larger than `SWARM_MAX_FILE_CHARS` (24000, what a worker can see whole) is refused, a rewrite that deletes more than `SWARM_MAX_DELETE_PCT` (50) percent of a file fails, and the new file must keep at least `SWARM_MIN_KEEP_PCT` (70) percent of the old file's size (a 70 line document came back as 3 lines in the second live run; PR closed) (the first live run turned a 340 line README into 38 lines; PR closed, never merged), and the kill switches of the swarm. Never editable: `.github/`, `ci/`, `deploy/secrets/`, `*.sops.yaml`, `CLAUDE.md`, `deploy/hermes/jobs/swarm*`, `deploy/hermes/jobs/claude-haiku`. Workers have no token and no shell: the script clones through the proxy, writes the files a worker returns, runs `make test` (and `scripts/check-sops.sh`), commits, pushes branch `swarm/<date>-<slug>` and opens the PR through the REST API. A failure deletes the work directory and pushes nothing.

**Run:** `make swarm-plan TASK=repo-work` (dry run: the picked task, derived `allowed_paths` and a scripted plan; no worker call, clone, push or PR), `make swarm-run TASK=repo-work`, `make swarm-status`. Register the cron entry paused with `register-cron.sh repo-work --apply`.

## Claude Haiku through the Claude Code CLI (spec 12)

Haiku runs on your Claude subscription, not the API. No API key exists anywhere; `claude-haiku.sh` unsets `ANTHROPIC_API_KEY` before each call and `make claude-haiku-preflight` fails if one is set.

**Image:** the CLI is baked into a custom image built on the pinned upstream Hermes image (`deploy/hermes/image/Dockerfile`), so nothing is downloaded or copied at runtime. Add other custom tools to that Dockerfile.
1. `scripts/build-hermes-image.sh [claude-code-version]` builds `dsm-shai/hermes:v0.23.1-1` and loads it into k3s (no registry; `imagePullPolicy: IfNotPresent`). Bump the tag in the script and `hermes.yaml` together when the image changes.
2. `claude setup-token`, then `scripts/set-claude-token.sh` (paste the token; SOPS-encrypted). Run `scripts/check-sops.sh`, commit, let Flux apply, then `kubectl -n hermes rollout restart deploy/hermes`.
3. `make claude-haiku-preflight`, then `echo "reply OK" | kubectl -n hermes exec -i deploy/hermes -- bash /opt/jobs/claude-haiku/claude-haiku.sh`.

**Use:** `claude-haiku.sh` reads the prompt on stdin and prints the answer. No tools are given to the model. Limits (env vars): `CLAUDE_HAIKU_PARALLEL` (2), `CLAUDE_HAIKU_DAILY_CALLS` (200), `CLAUDE_HAIKU_TIMEOUT` (120 s), `CLAUDE_HAIKU_MODEL` (`haiku`). Kill switch: `touch /opt/data/claude-haiku/disabled`. Audit: `/opt/data/claude-haiku/audit.jsonl` (no content).

**Data handling:** anything sent to Haiku is processed by Anthropic under your subscription's terms. Do not send memory dumps, secrets or personal data.

**Egress:** the Squid proxy now also allows `api.anthropic.com`, so the Hermes pod can reach that one extra host; other namespaces cannot. **Rotation:** new `claude setup-token`, re-run `set-claude-token.sh`, commit, restart Hermes, preflight, revoke the old token.

### Web research (spec 15)

`CLAUDE_HAIKU_WEB=1 claude-haiku.sh` lets Haiku search and read the public web. Only `WebSearch` and `WebFetch` exist in that mode (Bash, Edit, Write, Agent and MCP tools are disallowed, `dontAsk`, 12 turns, an empty working directory), and the CLI uses the open-web proxy listener (`CLAUDE_HAIKU_WEB_PROXY`, default `http://squid.egress-proxy.svc:3129`). Everything else in the pod keeps the restricted listener. Fetched pages are untrusted: wrap the answer in `UNTRUSTED_CONTENT` markers before acting on it, and do not send secrets or personal data in the prompt. Calls count against the same daily cap and kill switches. **Not yet verified in the cluster** (spec 15 lists the checks, including whether `WebSearch` works on the subscription token). Off: remove the `3129` rule from `deploy/hermes/egress-networkpolicy.yaml`, or `touch /opt/data/claude-haiku/disabled` to stop every Haiku call.

## Discord (spec 15, not built)

The gateway the pod already runs has a Discord adapter. The design (owner-only allowlist, swarm `quick_commands`, a digest cron that posts results, `discord_admin` off) and the open questions are in `specs/15-hermes-discord.md`. The egress for it is in place (restricted listener allows the Discord hosts); the secret, config and `swarm-chat.sh` are not.
