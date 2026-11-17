# Task List: Remaining Work

**As of 2026-11-16.** Only work still to do. Legend: `[ ]` not started, `[~]` started. Remove an item when it is done.

## 1. Merge PR #11 and verify

- [ ] Merge PR #11 (task list restart, spec 11). Then confirm Flux has reconciled `hermes` with `readOnlyRootFilesystem` (merged in #10): `kubectl -n hermes get pod`, then `hermes chat -q "..."` in the pod.

## 2. Spec 11: nightly specter improvement (new)

Spec: `specs/11-nightly-specter-improvement.md` (Status TODO). Depends on 04, 08, 09, 10.

- [ ] **Decide the open points:** `IMPL_PROBATION_NIGHTS` (spec default 7, `0` is full auto-merge from night 1); GitHub App token or fine-grained PAT; the exact `claude-specter` repo name and owner; the night window.
- [ ] **Egress proxy:** Squid pinned by digest in `egress-proxy`, SNI-checked allowlist for the five GitHub hosts in `deploy/istio/egress/`, hermes NetworkPolicy adds `:3128`, AuthorizationPolicy limits the proxy to the hermes service account, `HTTPS_PROXY` on the hermes pod. Negative and positive egress tests.
- [ ] **Token:** `deploy/secrets/hermes-github.sops.yaml`, added to `deploy/secrets/kustomization.yaml`, delivered as `GITHUB_TOKEN` in the hermes namespace only. Secret scan clean.
- [ ] **Job scripts** under `deploy/hermes/jobs/nightly-specter/`: `run.sh` (lock, timeout, dry run), `select_mode.py`, `inventory.py`, `dedupe.py`, `guard.py`, `validate`, versioned prompt files, unit tests with fixture repos.
- [ ] **Status and alerting:** `metrics.prom` and a read-only exporter on 9101, ServiceMonitor, alert rule, digest line, append-only audit log, OpenViking summary.
- [ ] **Hermes cron entry** (disabled until the rehearsal passes).
- [ ] **Rehearsal** on a throwaway fork of `claude-specter`: dry run, Mode A (up to 3 specs), Mode B (one implementation PR), forced-failure test, `hermes pause` test, one-PR-per-night test.
- [ ] **Go live:** point the job at the real repo, enable the cron, document in `deploy/hermes/README.md` (job, override, revert, token rotation and revocation), amend the egress and credential statements in specs 04, 08, 09 and 10, set the spec 11 index row to DONE or PARTIAL.

## 3. Open items that need you (not runnable from this session)

- [ ] **Step 1:** the `wsl --shutdown` restart test (stops the whole stack; check that all pods recover, and that pods ztunnel missed are listed in `deploy/istio/README.md`).
- [ ] **Step 1:** second run of the install scripts as a no-op (needs sudo).
- [ ] **Steps 10 and 12:** LAN-unreachable check for Open WebUI and Grafana from a second device.
- [ ] **Steps 10 and 12:** Windows browser check for `open-webui.localhost` and Grafana.
- [ ] **Step 13:** live restore over running PVCs (destructive).
- [ ] **Step 13:** fresh-cluster restore (needs a second install).
- [ ] **Step 13:** k3s datastore snapshot (needs root).
- [ ] **Step 13:** `wsl --export`.
- [ ] **Step 13:** observe a restic prune (needs about eight days of snapshots after 2026-11-16).

## 4. Housekeeping (small, safe to do any time)

- [ ] `specs/04-hermes-agent.md`: the acceptance line still says context 32768 and `qwen3:14b`. The live values are 65536 and `qwen3.5:9b`.
- [ ] Hermes: retest Tool Search with `qwen3.5:9b` (the `config.yaml` comment says it was only tested with `llama3.1:8b`).
- [ ] Hermes: test whether naming the LiteLLM alias after the model (so Hermes's model-name prompt tuning applies) changes behaviour (`deploy/hermes/README.md`, point 5).
- [ ] Benchmark `gemma4:12b` and `ministral-3:8b` (downloaded, not benchmarked) with `scripts/bench-hermes-tools.py`.

## 5. Proposed, not decided

- [ ] A recovery script that deletes pods ztunnel did not enrol after a restart, so `wsl --shutdown` recovery is not manual. (Raised after the 2026-11-16 incidents; no decision yet.)
- [ ] A first Hermes production job (a nightly cluster digest) with a verifier and a failure alert. Spec 11 is the first job in practice, so this may be folded into it.

## Not planned (decided out of scope)

Browser MCP tools, a hostname egress allowlist for anything other than the spec 11 GitHub hosts, SearXNG, activating the CI secret scan, and a LiteLLM fail-fast shorter than the 180 s timeout.
