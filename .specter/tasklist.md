# Task List: Remaining Work

**As of 2026-11-17.** Only work still to do. Legend: `[ ]` not started, `[~]` started. Remove an item when it is done.

## 1. Merge the spec 11 implementation PR and verify the rollout

- [ ] Merge the PR. Flux then recreates the hermes pod (new container, `Recreate`), adopts the `hermes-egress` NetworkPolicy, and creates the `egress-proxy` namespace and the Squid proxy.
- [ ] Delete the hermes pod once (ztunnel does not re-enrol running pods), then check `kubectl -n hermes get pod` is `2/2`, `hermes chat -q "..."` answers, and OpenViking and LiteLLM still work.
- [ ] Check all Flux stages are Ready, including the new `egress` stage.

## 2. Spec 11: nightly specter improvement (built, inert)

Built and tested offline: scripts, prompts, 33 local tests, proxy and policy manifests, alerts, Flux wiring. Open:

- [ ] **Squid proxy first run in the cluster.** Config and pod restrictions were verified in Docker (allow and deny work). Run the in-cluster checks in `deploy/istio/egress/README.md`, "Verify before use (in the cluster)".
- [ ] **In-pod preflight:** `bash /opt/jobs/nightly-specter/run.sh --preflight`.
- [ ] **Decide:** the probation default (`IMPL_PROBATION_NIGHTS`, 7 now; `0` is full auto-merge from night 1), token type (fine-grained token or GitHub App), the target repo `owner/name`, the night window.
- [ ] **Create the token** and the encrypted `deploy/secrets/hermes-github.sops.yaml` (steps in `deploy/hermes/README.md`, "Going live"). Verify the token cannot reach another repo or push to `.github/workflows/`.
- [ ] **Set `NIGHTLY_REPO`** to a throwaway fork of `claude-specter` first.
- [ ] **Rehearse on the fork:** dry run, Mode A (up to 3 specs), Mode B (one implementation PR), forced failure, `hermes pause`, one-PR-per-night.
- [ ] **Register the cron entry paused** with `register-cron.sh`; check that `hermes cron create --script` accepts the path.
- [ ] **Go live:** point `NIGHTLY_REPO` at the real repo, `hermes cron resume`, confirm the first night's audit and digest, then set the spec 11 index row to DONE.

## 3. Open items that need you (not runnable from this session)

- [ ] **Step 1:** the `wsl --shutdown` restart test (stops the whole stack; check that all pods recover, and note any pod ztunnel missed in `deploy/istio/README.md`).
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

- [ ] A recovery script that deletes pods ztunnel did not enrol after a restart, so `wsl --shutdown` recovery is not manual. (Seen again on 2026-11-16: `postgres-0`, `openviking`, `prometheus-0`.)

## Not planned (decided out of scope)

Browser MCP tools, a hostname egress allowlist for anything other than the spec 11 GitHub hosts, SearXNG, activating the CI secret scan, and a LiteLLM fail-fast shorter than the 180 s timeout.
