# dsm-shai operations. `make help` lists the targets. Everything here wraps kubectl, flux, systemd and the scripts/
# directory; nothing is installed or changed beyond what the target says.
SHELL       := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

NIGHTLY := /opt/jobs/nightly-specter/run.sh
STATE   := /opt/data/nightly-specter
# Run a command in the Hermes container. The pod prints a harmless "install out of sync" line; hide it.
HERMES  = kubectl -n hermes exec deploy/hermes -c hermes --
QUIET   = 2>&1 | grep -v 'install out of sync' || true

# A task is passed to the pod through the environment, so quotes and $ in it cannot break the command line.
export TASK
export REASON

.PHONY: help start stop status verify hermes-task hermes-pause hermes-resume \
        claude-haiku-preflight nightly-preflight nightly-dry-run nightly-run nightly-status test

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-z-]+):.*## /\1\t/' | awk -F'\t' '{printf "  %-18s %s\n", $$1, $$2}'

# ---- cluster -----------------------------------------------------------------------------------------------------
start: ## Start k3s and wait for the node (needs sudo)
	@# Docker Desktop mounts a 9p path with a space ("Program Files") at /Docker/host; the unescaped space gives
	@# /proc/mounts a 7-field line and the kubelet crash-loops ("wrong number of fields"). Unmount it first.
	@if awk 'NF!=6 {found=1} END {exit !found}' /proc/mounts; then \
		echo "Unmounting Docker Desktop's /Docker/host (breaks the kubelet's /proc/mounts parsing)"; \
		sudo umount /Docker/host; \
	fi
	sudo systemctl start k3s
	@echo "Waiting for the API server..."
	@timeout 180 sh -c 'until kubectl get nodes >/dev/null 2>&1; do sleep 3; done' || { echo "API server did not come up: journalctl -u k3s -n 50"; exit 1; }
	kubectl wait --for=condition=Ready node --all --timeout=180s
	@$(MAKE) --no-print-directory status
	@echo "After a restart, pods ztunnel did not enrol may hang: see deploy/istio/README.md, 'Restart recovery'."

stop: ## Stop k3s and every container, frees the GPU (asks first; YES=1 skips; needs sudo)
	@if [ "$(YES)" != "1" ]; then read -r -p "Stop k3s and ALL workloads (Ollama, Hermes, everything)? [y/N] " a; [ "$$a" = y ] || { echo aborted; exit 1; }; fi
	sudo /usr/local/bin/k3s-killall.sh

status: ## Node, Flux stages and any pod that is not Running or Completed
	@echo "k3s: $$(systemctl is-active k3s || true)"
	@kubectl get nodes
	@flux get kustomizations
	@kubectl get pods -A --no-headers | grep -vE 'Running|Completed' || echo "all pods Running or Completed"

verify: ## Run the host checks (scripts/30-verify.sh)
	scripts/30-verify.sh

# ---- Hermes ------------------------------------------------------------------------------------------------------
hermes-task: ## One-off task for Hermes: make hermes-task TASK="what to do"
	@test -n "$$TASK" || { echo 'usage: make hermes-task TASK="what to do"'; exit 2; }
	@$(HERMES) env "TASK=$$TASK" sh -c 'exec hermes -z "$$TASK"' $(QUIET)

hermes-pause: ## Emergency stop: no new Hermes turns or cron runs (REASON="why")
	@$(HERMES) hermes pause --reason "$${REASON:-paused with make}" $(QUIET)

hermes-resume: ## Lift the emergency stop
	@$(HERMES) hermes resume $(QUIET)

# ---- nightly specter job (spec 11) -------------------------------------------------------------------------------
nightly-preflight: ## Check the job's tools and state directory in the pod
	@$(HERMES) bash $(NIGHTLY) --preflight $(QUIET)

nightly-dry-run: ## Start a dry run in the pod, in the background (nothing pushed or merged); see nightly-status
	@$(HERMES) sh -c 'mkdir -p $(STATE) && ( nohup bash $(NIGHTLY) --dry-run > $(STATE)/dry-run.log 2>&1 & ) ; sleep 2; echo "dry run started; log: $(STATE)/dry-run.log"' $(QUIET)

nightly-run: ## Real run: opens and may MERGE pull requests in the target repo (needs CONFIRM=1)
	@test "$(CONFIRM)" = "1" || { echo "This opens and may merge PRs in NIGHTLY_REPO. Re-run with CONFIRM=1."; exit 2; }
	@$(HERMES) bash $(NIGHTLY) $(QUIET)

nightly-status: ## Is it running, last audit entries, digest, metrics
	@$(HERMES) sh -c 'pgrep -f "[o]rchestrate.py" >/dev/null && echo "RUNNING" || echo "not running"; echo "--- audit (last 3)"; tail -3 $(STATE)/audit.jsonl | cut -c1-400; echo "--- digest"; tail -5 $(STATE)/digest.log; echo "--- metrics"; cat $(STATE)/metrics.prom 2>/dev/null | grep -v "^#" || true' $(QUIET)

claude-haiku-preflight: ## Spec 12: is the Claude CLI and subscription token present in the pod (no call made)
	@$(HERMES) bash /opt/jobs/claude-haiku/claude-haiku.sh --preflight $(QUIET)

test: ## Run the nightly job's offline tests (no cluster needed)
	sh deploy/hermes/jobs/nightly-specter/tests/run_tests.sh
