# Task List: Remaining Work

**As of 2026-11-20.** Only work still to do. Legend: `[ ]` not started, `[~]` started. Remove an item when it is done. Sizes: S under an hour, M a session, L several sessions or needs you.

Markers: `[swarm]` = queued for the Hermes swarm (small, one named file; the repo maintainer merges what it opens); `[needs-owner]` = not for the swarm (needs the cluster, a second device, a decision, or a file too large for a worker). Section S is the swarm queue; the maintainer's `auto_queue` may add `[swarm]` to short tasks that name one to three small existing files.

## P. Priority (from Hermes's own state, 2026-11-25)

Ordered by what the Hermes state database shows going wrong or being asked for. Work top to bottom.

- [ ] [needs-owner] **Swarm repo-work verifier failures (S to M):** `digest.log` shows 24 `repo-work failed: step s1 failed its verifier` (17 on 2026-11-20, 6 on 2026-11-21) and one `arch-diagram` failure. Read the verifier output under `/opt/data/swarm/runs/` for those runs, find the cause, record it in `deploy/hermes/README.md`, and fix the verifier or the task format. Do this before the next unattended run.
- [ ] [needs-owner] **Hermes terminal-tool reliability (S):** several recent Hermes sessions restate "use only your terminal tool, not web search" to get a `curl` run. Settle the `make hermes-task` example (the existing item in section 6) and add the fix to `deploy/hermes/README.md`.

## S. Swarm queue (small tasks the swarm does, one file each)

Order matters only where a task says "after"; the swarm takes the first queued task and the maintainer merges its pull request before the next starts. Only the edited file is in backticks.

- [ ] [needs-owner] **Architecture, diagram:** in `docs/architecture.md` replace the code block under the heading "Architecture Diagram (Conceptual)" with a clean, aligned ASCII box diagram with no stray characters. Top to bottom: the Windows 11 host (i7-13700KF, RTX 4080 16 GB); WSL2 on ext4 running the k3s cluster with the Istio ambient mesh; a row of namespace boxes: ollama (inference), openviking (memory), litellm (gateway), hermes (agent, swarm, maintainer), open-webui, monitoring, flux-system; the Istio ingress gateway on the left feeding open-webui and grafana (host-local only); an egress-proxy box (Squid) below hermes leading to an External box that lists GitHub, api.anthropic.com and Discord hosts. Keep the code fence and the heading and change nothing outside the code block.

## S2. CI checks (each task creates one new script; make test now runs them all)

The checks run through the check target and as part of make test, so the repo maintainer runs them in a fresh clone of every pull request. Workflow files under the CI directories are off limits to the swarm and the token has no workflow scope, so this is the CI.

- [ ] [swarm] **CI check, markdown links:** create the new file `scripts/check-markdown-links.py`, a Python 3 script that uses only the standard library and no network; the file is Python, not bash. It starts with a shebang line (env python3) and a comment line saying what the check enforces. Run from the repository root, it lists tracked files with git ls-files and reads every .md file as UTF-8 (a file that is not valid UTF-8 is reported as PATH: not valid UTF-8 and counts as a problem). In each file it ignores fenced code blocks and inline code spans (text between backticks), because they hold examples; in the rest it finds relative markdown links of the form `](target)`, ignores targets that start with http://, https://, mailto: or #, strips any #fragment, resolves a target that starts with a slash from the repository root and any other target relative to the directory of the file, and reports each link whose target does not exist. Print one line per problem in exactly this form: PATH:LINE: broken link: TARGET, then exit 1. When clean, print exactly OK markdown-links and exit 0. It must exit 0 on the repository as it is today, because make test runs every check on every later pull request, so run it from the repository root and state the result. scripts/check-all.sh runs it through python3, so the file mode does not matter. Create only this one file.
  - Previous attempts (closed by the maintainer, PRs #146, #147, #149; #150 closed as superseded). Each new attempt must fix these:
    - No evidence the script was run. The check must exit 0 on the current repository, and the PR must show that run.
    - The link regex matches `](...)` inside fenced code blocks and inline code. Skip both before matching.
    - Absolute targets such as `/docs/x.md` are joined onto the file's directory and reported as missing. Resolve them from the repository root, or skip them.
    - `open(..., encoding='utf-8')` with no error handling crashes on a non-UTF-8 `.md` file. Report it on its line in the `path: message` format instead.
- [ ] [swarm] **CI check, token patterns:** create the new file `scripts/check-no-tokens.py`. It scans every tracked text file except names ending in .sops.yaml (skip files that are not valid UTF-8) for token-shaped strings: gh followed by one of p, o, u, s, r, an underscore and 36 or more letters or digits; github_pat_ followed by 22 or more letters, digits or underscores; sk-ant- followed by 20 or more letters, digits, hyphens or underscores. Build each regular expression from string fragments joined at run time so that this file does not itself contain a complete literal prefix, and report the file and line number (never the matched text). Use only bash and coreutils (a python3 check uses only the standard library); no network; run from the repository root and list files with git ls-files. Print one line per problem as path: message, then exit 1; print OK followed by the check name and exit 0 when clean. It must exit 0 on the repository as it is today, because make test runs every check on every later pull request. Start with a shebang line and a comment line saying what the check enforces. Create only this one file.
  - Previous attempts (closed by the maintainer, PRs #155 to #166, about ten in all). Each new attempt must fix these:
    - No evidence the script was run. The check must exit 0 on the current repository, and the PR must show that run.
    - The output format is `path:lineno: message`. The task says `path: message`, so the line number is a deviation to remove or to state in the PR.
    - The success line is `OK no-tokens`. The task says `OK` followed by the check name, which is `token patterns`.
    - The diff does not show that the file is executable. Confirm the mode, or invoke it through python3 in the Makefile.
- [ ] [swarm] **CI check, task list lint:** create the new file `scripts/check-task-list.py`, a Python 3 script that uses only the standard library and no network. The file is Python, not bash. It starts with a shebang line (env python3) and a comment line saying what the check enforces. It reads .specter/tasklist.md from the repository root and checks every line that starts with - [ ] [swarm] or - [ ] [needs-owner]: the line must contain between one and three backticked tokens that look like repository paths (contain a slash or end in a file extension); none of those paths may start with .github/, ci/, deploy/secrets/, deploy/hermes/jobs/swarm or deploy/hermes/jobs/claude-haiku, end in .sops.yaml, or equal CLAUDE.md; the owner-only marker must not appear in the tag before the bold title (a mention of it inside the description is fine); and the line must not sit under a heading whose text contains needs you at the machine, proposed, not decided or not planned (case-insensitive). Print one line per problem in exactly this form: .specter/tasklist.md:LINE: message (LINE is the line number), then exit 1. When clean, print exactly OK task-list-lint and exit 0. If .specter/tasklist.md is missing, print .specter/tasklist.md: missing and exit 1. It must exit 0 on the repository as it is today, because make test runs every check on every later pull request, so run it from the repository root and state the result. scripts/check-all.sh runs it through python3, so the file mode does not matter. Create only this one file.
- [ ] [swarm] **CI check, spec consistency:** create the new file `scripts/check-spec-consistency.py`. It checks the specs. For each file specs/NN-name.md: it has a line starting with **Status:**, and a row for NN in specs/00-index.md; the first word of the status in the spec (DONE, PARTIAL, IN, TODO) matches the first word of the status cell in the index row (treat PARTIAL and IN PROGRESS as the same group); a spec whose status starts with DONE has no unchecked acceptance box (a line starting with - [ ]). These are warnings today because some specs are known to disagree: print each as WARN path: message and exit 0, but exit 1 when the environment variable STRICT is set to 1. Use only bash and coreutils (a python3 check uses only the standard library); no network; run from the repository root and list files with git ls-files. Print each problem as described above; print OK followed by the check name and exit 0 when clean. It must exit 0 on the repository as it is today (warnings do not fail), because make test runs every check on every later pull request. Start with a shebang line and a comment line saying what the check enforces. Create only this one file.
- [ ] [swarm] **CI checks, documentation:** create the new file `docs/ci-checks.md`: a short page (under 60 lines) titled CI checks that explains that make test runs bash scripts/check-all.sh, which runs every script named scripts/check-*.sh and scripts/check-*.py, and that the repo maintainer runs make test in a fresh clone of every swarm pull request before it can merge; then a table with the columns Check and What it enforces for these checks: shell syntax, shebangs, python syntax, json validity, yaml tabs, line endings, large files, markdown links, kustomize references, makefile help, token patterns, task list lint, spec consistency (the last one only warns unless STRICT=1); then a section on how to add a check (put a script in scripts, exit non-zero on a problem, it must pass on the repository as it is). Create only this one file.

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

- [ ] [needs-owner] **Verify the Squid config (S):** `squid -k parse`, then the allow and deny checks for `:3128` and `:3129` in Docker (uid 13, read-only root); after Flux applies it, the in-cluster checks in `deploy/istio/egress/README.md` for both ports. Docker did not respond on 2026-11-18.
- [ ] [needs-owner] **Live research check (S):** `CLAUDE_HAIKU_WEB=1 claude-haiku.sh` in the pod; confirm `WebSearch` works on the subscription token, the tool list is exactly the two tools, and the Squid log shows `:3129`.
- [ ] [needs-owner] **Needs you (S):** create the Discord application and bot (Message Content Intent on, Server Members Intent off), invite it to a private server, give me the token, your user ID and the channel ID through `sops`; I never see them in plaintext in the repo.
- [ ] [needs-owner] **`quick_commands` test (S):** on a throwaway command, find out whether the LLM is bypassed, how arguments and stdout and the exit code behave, the timeout and working directory, and whether a non-admin is blocked.
- [ ] [needs-owner] **Build with `/do-spec` (L):** the `hermes-discord` secret, gateway config (`discord_admin` off, allowlists), `swarm-chat.sh` with offline tests, the digest cron script copied into `HERMES_HOME/scripts`, README, then the live criteria.

## 3. Real work I can do without you

- [ ] [needs-owner] **Mesh metrics and dashboard (M; closes the open item in specs 06 and 08):** scrape istiod, ztunnel and the ingress gateway with a ServiceMonitor or PodMonitor in `deploy/monitoring/`, provision an Istio dashboard in Grafana, check the series in Prometheus, record it in `deploy/monitoring/README.md` and `deploy/istio/README.md`.
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

- [ ] [needs-owner] Add a `make hermes-task` example to `deploy/hermes/README.md`: the 9B model needs the tool, the working directory and the GitHub REST call for the PR spelled out.
- [ ] [needs-owner] Trim `docs/architecture.md` to a real one-pager: fix the garbled diagram and the host RAM row (WSL exposes about 15 GB by default, not 24 GB).
- [ ] [needs-owner] Decide whether to name the model instead of the alias `chat` (scored 40/40 vs 38/40 in one run of 5, and changes Hermes's system prompt; see `deploy/hermes/README.md`). Test on a real multi-step task first. Needs the LiteLLM key allowlist to permit the new name.

## 7. Proposed, not decided

- [ ] Revisit mesh-native egress (ambient waypoint plus ServiceEntry) instead of Squid when upstream ztunnel can deny unregistered destinations, or when mesh identity and telemetry on egress are wanted (options and triggers in `deploy/istio/egress/README.md`).

## Not planned (decided out of scope)

Browser MCP tools, a hostname egress allowlist for anything other than the spec 11 GitHub hosts, SearXNG, activating the CI secret scan, and a LiteLLM fail-fast shorter than the 180 s timeout. Section 2 amends the specs to say so.
