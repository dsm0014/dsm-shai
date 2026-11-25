---
name: swarm-status
description: Report the state of the dsm-shai swarm and the cluster it runs on: infrastructure health, what is running now, the queued [swarm] tasks, open swarm pull requests, recent outcomes, and when the next maintainer tick and health check run. When a problem is found and remediation is asked for, queue the swarm-fixable fixes in the task list and open a PR. Use when asked for swarm status, what the swarm is doing, what is queued, when the next swarm step runs, or to remediate swarm issues.
---

# Swarm status

Run the status script from the repository root and report what it prints. The status run itself is read-only: no pod deletes, no kill switches, no cluster changes. When it finds a problem, it queues the problem's fix for the swarm if the swarm can make it (a task-list item and a PR, see Remediation below). Owner-only fixes are reported with the command that would fix them, and they wait for the owner to say go.

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

## Remediation: queue the swarm-fixable issues and open a PR

Run this only when the script found a problem, and only if the owner asked for remediation (the default run stays read-only).

1. **Classify each problem.**
   - **Swarm-fixable:** the fix is a text change to one to three repository files that the swarm may edit: a script under `scripts/` or `deploy/hermes/jobs/`, a README or doc, or a Makefile target. Examples: a check script that rejects valid input, a status script that prints the wrong value, a README that describes a fix wrongly.
   - **Owner-only:** anything on the cluster or the host: deleting or restarting pods, Flux reconciles, suspending or resuming a CronJob, removing kill-switch files, config in the cluster, or a manifest change (manifests need `[swarm-deploy]` and a careful review). Also anything the swarm may not edit: `.github/`, `ci/`, `deploy/secrets/`, `*.sops.yaml`, `CLAUDE.md`, `deploy/hermes/jobs/swarm*`, `deploy/hermes/jobs/claude-haiku`. Report these; do not queue them.
2. **Skip duplicates.** For each swarm-fixable problem, search `.specter/tasklist.md` and the open PRs for the same subject. If one already exists, do not add it again.
3. **Write one `[swarm]` item per problem** in section S, the swarm queue, before the S2 heading. Use the existing format: `- [ ] [swarm] **<short title>:** <what to change, with the file in backticks>. <the acceptance check>. Create or edit only the named file(s).` Name no more than three files. Include the check that proves it, such as `make test passes` or `bash scripts/swarm-status.sh prints OK for this line`.
4. **Open a PR** if at least one item was added:
   - Branch `chore/swarm-queue-<YYYYMMDD>-<slug>` from an up-to-date `main`.
   - Commit only the task-list edit, with a message that says which problems were queued and why, and the Co-Authored-By line.
   - Push with `-u`, and open the PR with `gh pr create --base main`. The body lists each problem, the evidence from the status run, and the test plan.
   - Do not merge it. The maintainer or the owner merges.
5. **Report** what was queued, the PR number, and the owner-only problems that still need a decision or a cluster change.

## Notes

- The maintainer runs every 15 minutes (`:00`, `:15`, `:30`, `:45` UTC). A tick merges any swarm PR that passes its gates, then starts repo-work on the first queued task if no swarm PR is open.
- The OpenViking extraction watch exits non-zero on purpose when it finds failed extractions. The script shows its last message on its own line, and that is not an unhealthy pod.
- Known-safe fixes, which need owner approval before running: `make mesh-enrolment-fix` (deletes ambient pods that ztunnel did not enrol), and removing a kill-switch file on the Hermes pod.
- The script is `scripts/swarm-status.sh`. The health check that runs every 30 minutes is `scripts/swarm-health.sh`; use its log at `~/.local/state/dsm-shai/swarm-health.log` if the owner asks what it found.
