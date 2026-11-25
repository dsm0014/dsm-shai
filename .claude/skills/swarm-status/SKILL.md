---
name: swarm-status
description: Report the state of the dsm-shai swarm and the cluster it runs on: infrastructure health, what is running now, the queued [swarm] tasks, open swarm pull requests, recent outcomes, and when the next maintainer tick and health check run. Use when asked for swarm status, what the swarm is doing, what is queued, or when the next swarm step runs.
---

# Swarm status

Read-only. Run the status script from the repository root and report what it prints. Do not change anything: no pod deletes, no pushes, no PR actions, no kill switches. If something is wrong, say what it is and which command would fix it, and wait for the owner to say go.

## Steps

1. Run `bash scripts/swarm-status.sh` from the repository root. It takes about a minute, because it queries the cluster, GitHub and the Hermes pod. Give it a timeout of at least 5 minutes.
2. Report the sections in this order, as short bullets:
   - **Infrastructure:** nodes, Flux, the ready replicas for Hermes, LiteLLM, Ollama, OpenViking, Squid and Prometheus, unhealthy pods, mesh enrolment, the maintainer CronJob, config values, kill switches, and GitHub reachability from Hermes. Flag anything not ready or not OK first.
   - **Running now:** the maintainer job in progress (if any), the swarm locks held, and the latest swarm run.
   - **Queued tasks:** the number on `main` and the titles. A task marked `[in review: PR #N]` is already being worked on.
   - **Open swarm PRs:** each one with its title.
   - **Recent outcomes:** the last maintainer and swarm digest lines, one line each.
   - **Next steps:** the next maintainer tick in UTC and minutes away, and the next health check. Repo-work starts on a tick only when no swarm PR is open, so say which case applies.
3. End with one line: "Healthy", or "Attention: " followed by the items that need action.

## Notes

- The maintainer runs every 15 minutes (`:00`, `:15`, `:30`, `:45` UTC). A tick merges any swarm PR that passes its gates, then starts repo-work on the first queued task if no swarm PR is open.
- The OpenViking extraction watch exits non-zero on purpose when it finds failed extractions. The script shows its last message on its own line, and that is not an unhealthy pod.
- Known-safe fixes, which need owner approval before running: `make mesh-enrolment-fix` (deletes ambient pods that ztunnel did not enrol), and removing a kill-switch file on the Hermes pod.
- The script is `scripts/swarm-status.sh`. The health check that runs every 30 minutes is `scripts/swarm-health.sh`; use its log at `~/.local/state/dsm-shai/swarm-health.log` if the owner asks what it found.
