# Specs Index

Status as of 2026-11-16. "DONE" means every acceptance criterion is verified. "PARTIAL" means the stated open items remain. The open items are listed in `.specter/tasklist.md`. The closed build list and decisions log are in `.specter/archive/`.

| # | Spec | Status | Open items |
|---|------|--------|-----------|
| 01 | [Platform Foundation](./01-platform-foundation.md) | IN PROGRESS | `wsl --shutdown` restart test (not run from inside the distro); second-run no-op check; `deploy/README.md` bootstrap order |
| 02 | [Ollama Inference](./02-ollama-inference.md) | DONE | Amended: chat model `qwen3.5:9b` (thinking on), context 65536 (see the amendments) |
| 03 | [OpenViking Context Service](./03-openviking-context.md) | DONE | Read-only root filesystem (not in the spec's criteria) |
| 04 | [Hermes Agent](./04-hermes-agent.md) | PARTIAL | Browser MCP tools; LiteLLM MCP gateway registration; hostname egress allowlist |
| 05 | [Web UI Ingress](./05-web-ui-ingress.md) | PARTIAL | Windows and LAN reachability checks; Open WebUI egress limited to LiteLLM and DNS |
| 06 | [Observability](./06-observability.md) | PARTIAL | Mesh metrics and dashboard; LAN and Windows checks |
| 07 | [Secrets Management and Backup/Restore](./07-secrets-backup.md) | PARTIAL | Live and fresh-cluster restore; k3s datastore snapshot (needs root); `wsl --export` not run; prune not yet observed |
| 08 | [Istio Service Mesh](./08-istio-service-mesh.md) | PARTIAL | Hostname egress allowlist; Grafana and mesh metrics (step 12) |
| 09 | [LiteLLM Gateway](./09-litellm-gateway.md) | PARTIAL | MCP and browser registration; consumer integrations (done for OpenViking, Hermes and Open WebUI); Istio deny (done); fail-fast on Ollama outage (bounded by a 180 s timeout) |
| 10 | [GitOps with Flux](./10-flux-gitops.md) | PARTIAL | CI secret scan stays inactive (the `workflow` token scope is not added; the pre-commit scan is active); everything else per `.specter/archive/tasklist-specs-01-10-2026-11-16.md` step 2 |
| 11 | [Nightly Specter Improvement](./11-nightly-specter-improvement.md) | TODO | Not started. Needs the GitHub egress proxy (amends the spec 08 hostname decision), a repo-scoped GitHub token (amends spec 10), and the job scripts |

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
