# Task List: Remaining Work

**As of 2026-11-20.** Only work still to do. Legend: `[ ]` not started, `[~]` started. Remove an item when it is done. Sizes: S under an hour, M a session, L several sessions or needs you.

Markers: `[swarm]` = queued for the Hermes swarm (small, one named file; the repo maintainer merges what it opens); `[needs-owner]` = not for the swarm (needs the cluster, a second device, a decision, or a file too large for a worker). Section S is the swarm queue; the maintainer's `auto_queue` may add `[swarm]` to short tasks that name one to three small existing files.

## P. Priority (from Hermes's own state, 2026-11-25)

Ordered by what the Hermes state database shows going wrong or being asked for. Work top to bottom.


## S. Swarm queue (small tasks the swarm does, one file each)

Order matters only where a task says "after"; the swarm takes the first queued task and the maintainer merges its pull request before the next starts. Only the edited file is in backticks.


## S2. CI checks (each task creates one new script; make test now runs them all)

The checks run through the check target and as part of make test, so the repo maintainer runs them in a fresh clone of every pull request. Workflow files under the CI directories are off limits to the swarm and the token has no workflow scope, so this is the CI.

  - Previous attempts (closed by the maintainer, PRs #146, #147, #149; #150 closed as superseded). Each new attempt must fix these:
    - No evidence the script was run. The check must exit 0 on the current repository, and the PR must show that run.
    - The link regex matches `](...)` inside fenced code blocks and inline code. Skip both before matching.
    - Absolute targets such as `/docs/x.md` are joined onto the file's directory and reported as missing. Resolve them from the repository root, or skip them.
    - `open(..., encoding='utf-8')` with no error handling crashes on a non-UTF-8 `.md` file. Report it on its line in the `path: message` format instead.
  - Previous attempts (closed by the maintainer, PRs #155 to #166, about ten in all). Each new attempt must fix these:
    - No evidence the script was run. The check must exit 0 on the current repository, and the PR must show that run.
    - The output format is `path:lineno: message`. The task says `path: message`, so the line number is a deviation to remove or to state in the PR.
    - The success line is `OK no-tokens`. The task says `OK` followed by the check name, which is `token patterns`.
    - The diff does not show that the file is executable. Confirm the mode, or invoke it through python3 in the Makefile.

## 0. Swarms (specs 12, 13, 14)

Spec 13 is DONE (live-verified; the `swarm-example` cron entry is registered paused, resume it with `hermes cron resume 21b81355887d` when you want the nightly digest). Remaining:

- [ ] [needs-owner] **Ministral tool calls (S):** after an Ollama upgrade, test whether `ministral-3:14b` returns structured tool calls on its own; if so delete `deploy/litellm/ministral_tools.py` and its config lines and set Hermes `streaming` back to true.
- [ ] [needs-owner] **Hermes tool-use score on Ministral (S):** run the Hermes replay (`scripts/bench-hermes-tools.py`) against `ministral-3:14b` and record it next to the earlier qwen3.5:9b score in `deploy/hermes/README.md`.
- [~] **Spec 16 (repo maintainer):** deployed in `observe` mode as the CronJob `repo-maintainer` (every 30 minutes, comments once per PR head, never merges). To let it merge good swarm PRs, change `mode: observe` to `merge` (or `merge-and-run`) in `deploy/hermes/jobs/repo-maintainer/repos.yaml` in a reviewed PR; enable branch protection on `main` first. Open: a live merge-mode run, the CronJob's first scheduled pass, the `[needs-owner]` path live.
- [ ] [needs-owner] **Nightly and swarm cron (S):** Hermes cron scripts cannot get `GITHUB_TOKEN` (stripped by design), so the paused `swarm-repo-work` and the nightly specter entries would fail with a 401 when resumed. Move them to CronJobs like the maintainer (see `deploy/hermes/maintainer-cronjob.yaml`).
- [ ] [needs-owner] **Close spec 12 (S, needs you):** the console check is confirmed (owner, 2026-11-19). Remaining: one `vision` request through LiteLLM with the Open WebUI key (I will not use the master key). Then set spec 12 DONE.
- [~] **Spec 14 (autonomous repo work):** built, live-verified on this repo, cron entry registered paused. Open: flip `SWARM_REPO_WORK` to 1 in `swarm-env` when you want it unattended; check `skipped: pr open` and `make swarm-plan TASK=repo-work` live the next time a `[swarm]` task is queued; the rehearsal-repo run was skipped. Queue a task by adding `[swarm]` and a backticked file path (small files only, under 24000 characters).
- [ ] [needs-owner] **Hermes-native replacements (M; from `docs/hermes-features-audit.md`):** replace the `register-cron.sh` generators for `swarm-example` and `swarm-template` with the documented `hermes cron create --script ... --no-agent --paused` command in `deploy/hermes/README.md`, and move the `digest.log` delivery to Hermes cron `deliver` to a chat platform once Discord (spec 15) exists. Keep the offline tests passing.

## 0b. Spec 15: Discord, swarm commands, Haiku web research

Egress (two Squid listeners) and the wrapper's research mode are written and tested offline. Do these in order.

- [ ] [needs-owner] **Needs you (S):** create the Discord application and bot (Message Content Intent on, Server Members Intent off), invite it to a private server, give me the token, your user ID and the channel ID through `sops`; I never see them in plaintext in the repo.
- [ ] [needs-owner] **`quick_commands` test (S):** on a throwaway command, find out whether the LLM is bypassed, how arguments and stdout and the exit code behave, the timeout and working directory, and whether a non-admin is blocked.
- [ ] [needs-owner] **Build with `/do-spec` (L):** the `hermes-discord` secret, gateway config (`discord_admin` off, allowlists), `swarm-chat.sh` with offline tests, the digest cron script copied into `HERMES_HOME/scripts`, README, then the live criteria.

## 3. Real work I can do without you

- [ ] [needs-owner] **Alert fire tests (S to M; spec 06):** VRAM above a lowered threshold, a crash-looping test pod, PVC fill. Tick the criterion only if all three fire.
- [ ] [needs-owner] **Virtual keys survive a Postgres restore (S; spec 09):** run it as part of the spec 07 restore drill (section 4), then tick the spec 09 criterion.

## 4. Needs you at the machine

- [ ] **Spec 01:** second run of the install scripts as a no-op (sudo); `deploy/README.md` bootstrap order.
- [ ] **Specs 05 and 06:** from a second LAN device, Open WebUI and Grafana are unreachable; from a Windows browser, `open-webui.localhost` and Grafana load.
- [ ] **Spec 07 (destructive or needs root):** live restore over running PVCs; fresh-cluster restore (second install); k3s datastore snapshot (root); `wsl --export`; observe a restic prune (needs about eight days of snapshots after 2026-11-16).

## 5. Spec 11: nightly specter improvement (built, merged, inert)

- [~] **Rehearse on the rehearsal repo** (`dsm0014/claude-specter-auto`): the first dry run passed (Mode A, 3 specs, nothing pushed). Still to do: a second dry run to confirm the two bug fixes, a live Mode A run (spec PR merges), Mode B (implementation PR), forced failure, `hermes pause`, one-PR-per-night.
- [ ] [needs-owner] **Register the cron entry paused** with `register-cron.sh --apply` (it now writes the wrapper under `/opt/data/scripts`, the only place `--script` accepts).
- [ ] [needs-owner] **Go live:** point `NIGHTLY_REPO` at the real repo, `hermes cron resume`, confirm the first night's audit and digest, then set the spec 11 index row to DONE.

## 6. Housekeeping

- [ ] [needs-owner] Trim `docs/architecture.md` to a real one-pager (the diagram is fixed and the host RAM row already says WSL exposes about 15 GB by default): it is 278 lines, so deciding what to cut is yours.
- [ ] [needs-owner] Decide whether to name the model instead of the alias `chat` (scored 40/40 vs 38/40 in one run of 5, and changes Hermes's system prompt; see `deploy/hermes/README.md`). Test on a real multi-step task first. Needs the LiteLLM key allowlist to permit the new name.

## 7. Proposed, not decided

- [ ] Revisit mesh-native egress (ambient waypoint plus ServiceEntry) instead of Squid when upstream ztunnel can deny unregistered destinations, or when mesh identity and telemetry on egress are wanted (options and triggers in `deploy/istio/egress/README.md`).

## Not planned (decided out of scope)

Browser MCP tools, a hostname egress allowlist for anything other than the spec 11 GitHub hosts, SearXNG, activating the CI secret scan, and a LiteLLM fail-fast shorter than the 180 s timeout. Section 2 amends the specs to say so.
