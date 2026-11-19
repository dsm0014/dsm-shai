# CLAUDE.md

`dsm-shai` (self-hosted AI) is a local, autonomous AI stack on Kubernetes: Ollama (inference), OpenViking (agent context/memory database), and Hermes Agent (Nous Research autonomous agent), plus supporting components.

## Target Hardware (verified 2026-11-15)

- CPU: Intel i7-13700KF (16C/24T)
- GPU: NVIDIA RTX 4080, 16 GB VRAM (driver 610.x, CUDA 13.x exposed to WSL2)
- RAM: 32 GB host; WSL2 default exposes only ~15 GB (raise via `.wslconfig`)
- Disk: WSL ext4 volume ~950 GB free; Windows C: is 90% full, so keep model/PVC storage inside WSL
- Host: Windows 11 + WSL2, Docker Desktop present; no kubectl/helm/k3s/nvidia-ctk installed yet

## Design Constraints

- One 16 GB GPU is shared by all models: chat model (~14B Q4), embedding model, and a small VLM. Budget VRAM explicitly; models swap via Ollama keep-alive.
- Models of 30B+ do not fit and are out of scope.
- Agent context needs 32k-64k tokens; KV cache counts against the VRAM budget.
- Everything runs locally; no cloud model providers. One exception (spec 12): Claude Haiku through the Claude Code CLI on the owner's subscription (no API key, no API credits), callable only from the Hermes pod via `claude-haiku.sh`; LiteLLM never gets an Anthropic provider. Spec 15 adds a research mode to that wrapper (only `WebSearch` and `WebFetch`, through an open-web proxy listener), and Discord as the chat interface (outbound only, owner allowlist).
- Istio (ambient mode) provides mTLS, authorization, the single ingress gateway and hostname-level egress control (spec 08). The hermes pod leaves the cluster only through the Squid proxy (`deploy/istio/egress/`): a restricted listener (GitHub, Anthropic, Discord) and an open-web listener used only by Haiku research. Traefik is disabled.
- Flux (spec 10) is the delivery mechanism for everything in-cluster: ordered `dependsOn` rollout, in-cluster SOPS decryption, drift correction. The repo is public on GitHub, so never commit plaintext secrets or personal data; ciphertext only, scanned before commit.
- LiteLLM (free tier) is the only caller of Ollama and the routing gateway for models and MCP/browser tools (spec 09). Consumers use per-consumer virtual keys.

## Conventions

- Specs live in `specs/`, numbered sequentially (`NN-<slug>.md`) with Status, Purpose, Behavior, Acceptance Criteria. Update `specs/00-index.md` with each new spec.
- Specs are authored with `/new-spec` (claude-specter) and implemented with `/do-spec`.
- The task list (`.specter/tasklist.md`) holds only work still to do. When a task list is completed, archive it to `.specter/archive/` as a dated decision log and start the next list from the remaining work only. The new list does not repeat, summarise or link earlier lists; history lives in the archive.
- Kubernetes manifests are Helm/Kustomize under `deploy/`; scripts under `scripts/`.
