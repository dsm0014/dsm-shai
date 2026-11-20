# Specs Index

Status as of 2026-11-20. "DONE" means every acceptance criterion is verified. "PARTIAL" means the stated open items remain. The open items are listed in `.specter/tasklist.md`. The closed build list and decisions log are in `.specter/archive/`.

| # | Spec | Status | Open items |
|---|------|--------|-----------|
| 01 | [Platform Foundation](./01-platform-foundation.md) | IN PROGRESS | `wsl --shutdown` restart test (not run from inside the distro); second-run no-op check; `deploy/README.md` bootstrap order |
| 02 | [Ollama Inference](./02-ollama-inference.md) | DONE | Amended: chat model `qwen3.5:9b` (thinking on), context 65536 (see the amendments) |
| 03 | [OpenViking Context Service](./03-openviking-context.md) | DONE | Read-only root filesystem (not in the spec's criteria) |
| 04 | [Hermes Agent](./04-hermes-agent.md) | PARTIAL | Browser MCP and the LiteLLM MCP gateway registration are out of scope (decided: Hermes reaches OpenViking directly); hostname egress is the Squid proxy (specs 11 and 15); the acceptance boxes in the spec still need ticking against the README evidence |
| 05 | [Web UI Ingress](./05-web-ui-ingress.md) | PARTIAL | Windows and LAN reachability checks; Open WebUI egress limited to LiteLLM and DNS |
| 06 | [Observability](./06-observability.md) | PARTIAL | Mesh metrics and dashboard; LAN and Windows checks |
| 07 | [Secrets Management and Backup/Restore](./07-secrets-backup.md) | PARTIAL | Live and fresh-cluster restore; k3s datastore snapshot (needs root); `wsl --export` not run; prune not yet observed |
| 08 | [Istio Service Mesh](./08-istio-service-mesh.md) | PARTIAL | Hostname egress is the Squid proxy for the hermes pod (done); Grafana and mesh metrics (step 12) |
| 09 | [LiteLLM Gateway](./09-litellm-gateway.md) | PARTIAL | Browser MCP and the browser pod are out of scope (decided); MCP registration is OpenViking only; consumer integrations are done for OpenViking, Hermes and Open WebUI; Istio deny is done; an Ollama outage is bounded by the 180 s timeout; virtual keys surviving a Postgres restore is not yet checked |
| 10 | [GitOps with Flux](./10-flux-gitops.md) | PARTIAL | CI secret scan stays inactive (the `workflow` token scope is not added; the pre-commit scan is active); everything else per `.specter/archive/tasklist-specs-01-10-2026-11-16.md` step 2 |
| 11 | [Nightly Specter Improvement](./11-nightly-specter-improvement.md) | PARTIAL | Built, merged and running inert (proxy and preflight verified in the cluster). Open: GitHub token, `hermes pause` test, fork rehearsal, cron entry, go-live |
| 12 | [Claude Haiku via Claude Code CLI](./12-anthropic-litellm-key.md) | IN PROGRESS | Live: image, token, wrapper call and proxy path verified 2026-11-18. Egress gap closed with litellm and openviking egress policies; wrapper offline tests pass. Open: the Anthropic console API-usage check, LiteLLM vision regression check, and egress policies for ollama, monitoring and istio-system. Subscription only, no API key |
| 13 | [Hermes Swarm Orchestration](./13-hermes-swarm-orchestration.md) | DONE | Every criterion verified live 2026-11-19; the `swarm-example` cron entry is registered paused |
| 14 | [Autonomous Repo Work via the Swarm](./14-swarm-repo-work.md) | IN PROGRESS | Built and live-verified on this repo (7 merged swarm PRs). Open: rehearsal-repo run (skipped), `make swarm-plan TASK=repo-work` and `skipped: pr open` live, `SWARM_REPO_WORK=1` flip |
| 15 | [Hermes on Discord, Swarm Commands and Haiku Web Research](./15-hermes-discord.md) | IN PROGRESS | Egress (restricted and open-web proxy listeners) and the Haiku research mode are built and tested offline. Open: Squid check in Docker and in the cluster, research live check, the whole Discord side (secret, gateway, `quick_commands`, `swarm-chat.sh`, digest cron) |
| 16 | [Repo Maintainer Loop](./16-repo-maintainer-loop.md) | IN PROGRESS | Built and deployed on this repo as a Kubernetes CronJob (merge-and-run with auto_queue since 2026-11-20) (Hermes cron cannot carry the GitHub token); builds on specs 11, 12, 13, 14. Open: live merge-mode run, first scheduled pass, branch protection |

## Measured footprint (2026-11-16)

| Part | Measured |
|---|---|
| Ollama, chat `qwen3.5:9b` at 64K, embed, VLM | chat 6.43 GiB VRAM; with embed resident the device uses 9.7 GiB of 16 GiB (the earlier `llama3.1:8b` figures were 8.9 GiB and 11.8 to 12.9 GiB) |
| Istio mesh (istiod, ztunnel, ingress gateway, cni) | about 250 MiB (budget about 1.5 GB) |
| Monitoring (Prometheus, Grafana, KSM, operator, node-exporter, GPU exporter) | about 1.15 GiB |
| Hermes, OpenViking, Open WebUI, LiteLLM and Postgres | see `kubectl top pods` (small; OpenViking 2 GiB request) |

## WSL2 GPU metrics

DCGM is not used. The `nvidia-smi` exporter reports memory used and total, utilization, temperature, power and clocks. Per-process VRAM is not available on WSL2. See `deploy/monitoring/README.md`.

## Branches

All feature branches (`feat/ollama-verification` through `feat/backup`) are merged to `main`, and Flux reconciles all 13 stages from it (PR #9, `db4986c`).
