# Task List: Remaining Work

**As of 2026-11-18.** Only work still to do. Legend: `[ ]` not started, `[~]` started. Remove an item when it is done. Sizes: S under an hour, M a session, L several sessions or needs you.

Specs 01, 04 to 08 and 10 to 13 are not DONE. Most of the gap is bookkeeping (section 1), a few decided-out-of-scope criteria (section 2) and checks that need you at the machine (section 4). Real engineering is sections 3 and 5.

## 0. Priority: Haiku + Qwen swarms (specs 12 and 13)

Goal: Hermes works on the repo autonomously. Spec 12 (Haiku wrapper) is live; spec 13 (swarm) is reconciled with it and not built. Do these in order.

- [ ] **Close spec 12 (S):** verify `chat`/`embed`/`vision` through LiteLLM and that LiteLLM has no Anthropic config; grep logs and `audit.jsonl` for prompt, response or token content; add the data-handling statement, install steps and rotation to `CLAUDE.md` and `deploy/hermes/README.md`; tick the criteria. Needs you: the Anthropic console API-usage check.
- [ ] **Build spec 13 with `/do-spec` (L):** `route.py`, `swarm.py` (2 local, 2 Haiku), verifiers, state and audit, `swarm-*` Make targets, `swarm-template` and `swarm-example`, offline tests with a fake gateway. Then a live `swarm-example` run and the cron entry registered paused.
- [ ] **Spec 11 isolation guard (S, also in section 5):** do it first. The swarm reuses the same fail-closed repo rule (`SWARM_ALLOWED_REPOS`), because the GitHub token now covers all repos.
- [ ] **Spec 14, autonomous repo work (needs `/new-spec`):** a swarm job that takes a task from this tasklist, works in a branch, opens a PR for you to merge, and never merges itself. Write it only after the spec 13 live run passes.

## 1. Bookkeeping: make the spec files match what is already verified (S, one PR)

Specs 01, 04, 05, 06, 07, 08 and 10 have no acceptance box ticked, and 09 and 11 have 7 and 4 open, although most of those criteria were verified (evidence is in each `deploy/*/README.md`).

- [ ] For each of specs 01 to 11, tick every acceptance criterion that a `deploy/*/README.md` records as verified; leave the rest open. Then set each spec's status in `specs/00-index.md` from the remaining unticked boxes only, and refresh its "as of" date.

## 2. Amend criteria that were decided out of scope (S, one PR with section 1)

The decisions are made; the criteria still demand the work, so these specs cannot reach DONE as written.

- [ ] **Spec 04:** drop the browser MCP tools; reword "an allowlisted web host is reachable" to the five GitHub hosts through the Squid proxy (spec 11); record that Hermes reaches OpenViking directly, not through the LiteLLM MCP gateway (tool-surface problem with the 9B model).
- [ ] **Spec 08:** reword the hostname-allowlist criterion to the same GitHub-only proxy for the hermes pod (`REGISTRY_ONLY` does not block unregistered hosts in ambient).
- [ ] **Spec 09:** drop the browser MCP and browser pod criteria; reword "fails fast when Ollama is down" to "bounded by the 180 s timeout".
- [ ] **Spec 10:** reword the CI secret scan criterion to the pre-commit scan only (the `workflow` token scope is not added; the workflow file stays in `ci/`).
- [ ] **Spec 11 and `deploy/hermes/README.md` (step 1 of the GitHub token section):** the token is now fine-grained for all repositories (Contents and Pull requests read/write, Metadata read; no Administration, no Workflows; expires 2027-02-14), not a single repository. Update the wording, and the spec 10 amendment that says the hermes namespace holds a single-repo token.

## 3. Real work I can do without you

- [ ] **Mesh metrics and dashboard (M; closes the open item in specs 06 and 08):** scrape istiod, ztunnel and the ingress gateway with a ServiceMonitor or PodMonitor in `deploy/monitoring/`, provision an Istio dashboard in Grafana, check the series in Prometheus, record it in `deploy/monitoring/README.md` and `deploy/istio/README.md`.
- [ ] **Alert fire tests (S to M; spec 06):** VRAM above a lowered threshold, a crash-looping test pod, PVC fill. Tick the criterion only if all three fire.
- [ ] **Virtual keys survive a Postgres restore (S; spec 09):** run it as part of the spec 07 restore drill (section 4), then tick the spec 09 criterion.
- [ ] **Recovery script for pods ztunnel did not enrol after `wsl --shutdown` (S to M):** delete the affected pods automatically (seen on `postgres-0`, `openviking`, `prometheus-0`).

## 4. Needs you at the machine

- [ ] **Spec 01:** second run of the install scripts as a no-op (sudo); `deploy/README.md` bootstrap order.
- [ ] **Specs 05 and 06:** from a second LAN device, Open WebUI and Grafana are unreachable; from a Windows browser, `open-webui.localhost` and Grafana load.
- [ ] **Spec 07 (destructive or needs root):** live restore over running PVCs; fresh-cluster restore (second install); k3s datastore snapshot (root); `wsl --export`; observe a restic prune (needs about eight days of snapshots after 2026-11-16).

## 5. Spec 11: nightly specter improvement (built, merged, inert)

- [ ] **Isolation guard (S):** the token no longer limits the job to `claude-specter-auto`, so `NIGHTLY_REPO` is the only thing that does. Check that the job refuses any other target, and that a wrong `NIGHTLY_REPO` fails closed.
- [~] **Rehearse on the rehearsal repo** (`dsm0014/claude-specter-auto`): the first dry run passed (Mode A, 3 specs, nothing pushed). Still to do: a second dry run to confirm the two bug fixes, a live Mode A run (spec PR merges), Mode B (implementation PR), forced failure, `hermes pause`, one-PR-per-night.
- [ ] **Register the cron entry paused** with `register-cron.sh`; check that `hermes cron create --script` accepts the path.
- [ ] **Go live:** point `NIGHTLY_REPO` at the real repo, `hermes cron resume`, confirm the first night's audit and digest, then set the spec 11 index row to DONE.

## 6. Housekeeping

- [ ] Add a `make hermes-task` example to `deploy/hermes/README.md`: the 9B model needs the tool, the working directory and the GitHub REST call for the PR spelled out.
- [ ] Trim `docs/architecture.md` to a real one-pager: fix the garbled diagram and the host RAM row (WSL exposes about 15 GB by default, not 24 GB).
- [ ] Benchmark `gemma4:12b` and `ministral-3:8b` with `scripts/bench-hermes-tools.py` (not on the PVC now; pull first).
- [ ] Decide whether to name the model instead of the alias `chat` (scored 40/40 vs 38/40 in one run of 5, and changes Hermes's system prompt; see `deploy/hermes/README.md`). Test on a real multi-step task first. Needs the LiteLLM key allowlist to permit the new name.

## 7. Proposed, not decided

- [ ] Revisit mesh-native egress (ambient waypoint plus ServiceEntry) instead of Squid when upstream ztunnel can deny unregistered destinations, or when mesh identity and telemetry on egress are wanted (options and triggers in `deploy/istio/egress/README.md`).

## Not planned (decided out of scope)

Browser MCP tools, a hostname egress allowlist for anything other than the spec 11 GitHub hosts, SearXNG, activating the CI secret scan, and a LiteLLM fail-fast shorter than the 180 s timeout. Section 2 amends the specs to say so.
