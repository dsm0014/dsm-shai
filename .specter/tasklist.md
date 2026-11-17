# Task List: Remaining Work

**As of 2026-11-17 (after the spec 11 merge).** Only work still to do. Legend: `[ ]` not started, `[~]` started. Remove an item when it is done.

## 1. Spec 11: nightly specter improvement (built, merged, running inert)

Token and rehearsal repo done 2026-11-17: fine-grained token for `dsm0014/claude-specter-auto` only (verified: cannot see the private `claude-specter`, cannot push workflow files, cannot change settings), stored as `deploy/secrets/hermes-github.sops.yaml`; `NIGHTLY_REPO=dsm0014/claude-specter-auto`; probation 1; token expires 2027-02-14. Verified in the cluster on 2026-11-17: the Squid proxy (allow, deny, no bypass, other namespaces refused), the in-pod preflight, the mounted scripts under the read-only root, the unconfigured run (`not configured`, exit 0), and the Prometheus target and rules. Open:

- [ ] **Rehearse on the fork:** dry run, Mode A (up to 3 specs), Mode B (one implementation PR), forced failure, `hermes pause`, one-PR-per-night.
- [ ] **Register the cron entry paused** with `register-cron.sh`; check that `hermes cron create --script` accepts the path.
- [ ] **Go live:** point `NIGHTLY_REPO` at the real repo, `hermes cron resume`, confirm the first night's audit and digest, then set the spec 11 index row to DONE.

## 2. Fix PR in review

- [ ] Merge the PR that fixes the preflight (it checked the state directory before creating it) and the `NightlySpecterStale` alert (it would fire from the first scrape of a job that never ran).

## 3. Open items that need you (not runnable from this session)

- [ ] **Step 1:** second run of the install scripts as a no-op (needs sudo).
- [ ] **Steps 10 and 12:** LAN-unreachable check for Open WebUI and Grafana from a second device.
- [ ] **Steps 10 and 12:** Windows browser check for `open-webui.localhost` and Grafana.
- [ ] **Step 13:** live restore over running PVCs (destructive).
- [ ] **Step 13:** fresh-cluster restore (needs a second install).
- [ ] **Step 13:** k3s datastore snapshot (needs root).
- [ ] **Step 13:** `wsl --export`.
- [ ] **Step 13:** observe a restic prune (needs about eight days of snapshots after 2026-11-16).

## 4. Housekeeping

- [ ] Benchmark `gemma4:12b` and `ministral-3:8b` with `scripts/bench-hermes-tools.py` (not on the PVC now; pull first).
- [ ] Decide whether to name the model instead of the alias `chat` (scored 40/40 vs 38/40 in one run of 5, and changes Hermes's system prompt; see `deploy/hermes/README.md`). Test on a real multi-step task first. Needs the LiteLLM key allowlist to permit the new name.

## 5. Proposed, not decided

- [ ] Revisit mesh-native egress (ambient waypoint plus ServiceEntry) instead of Squid when upstream ztunnel can deny unregistered destinations, or when mesh identity and telemetry on egress are wanted. Squid was kept on 2026-11-17; the options and triggers are in `deploy/istio/egress/README.md`.

- [ ] A recovery script that deletes pods ztunnel did not enrol after a restart, so `wsl --shutdown` recovery is not manual. (Seen again on 2026-11-16: `postgres-0`, `openviking`, `prometheus-0`.)

## Not planned (decided out of scope)

Browser MCP tools, a hostname egress allowlist for anything other than the spec 11 GitHub hosts, SearXNG, activating the CI secret scan, and a LiteLLM fail-fast shorter than the 180 s timeout.
