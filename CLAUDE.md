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
- Everything runs locally; no cloud model providers.

## Conventions

- Specs live in `specs/`, numbered sequentially (`NN-<slug>.md`) with Status, Purpose, Behavior, Acceptance Criteria. Update `specs/00-index.md` with each new spec.
- Specs are authored with `/new-spec` (claude-specter) and implemented with `/do-spec`.
- Kubernetes manifests are Helm/Kustomize under `deploy/`; scripts under `scripts/`.
