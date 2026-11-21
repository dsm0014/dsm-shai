# dsm-shai — High-Level Architecture Overview

**Linked from README:** See [`specs/00-index.md`](../specs/00-index.md) for the build plan and spec catalog.

---

## Purpose

`dsm-shai` is a self-hosted, autonomous AI stack running locally on Windows 11 + WSL2 with a single NVIDIA RTX 4080 (16 GB). It orchestrates Ollama (inference), OpenViking (memory/knowledge database), and Hermes Agent (autonomous task execution) on a single-node k3s cluster behind an Istio service mesh. All model inference runs locally via the free-tier LiteLLM gateway; no cloud providers are used.

---

## Target Hardware

| Component                | Specification                              |
|--------------------------|--------------------------------------------|
| CPU                      | Intel i7-13700KF (16C/24T)                |
| GPU                      | NVIDIA RTX 4080, 16 GB VRAM               |
| Host RAM                 | 32 GB (WSL exposed: ~15 GB default)        |
| Disk                     | WSL ext4 volume (~950 GB free)             |
| Host OS                  | Windows 11                                 |
| Cluster                  | k3s single-node, containerd, GPU plugin    |

**Constraints:**
- The 16 GB GPU is shared by chat model (~14B Q4), embedding, and VLM. Models swap via Ollama keep-alive.
- 30B+ models do not fit and are out of scope.
- KV cache counts against the VRAM budget; agent context requires 32k–64k tokens.

---

## Architecture Diagram (Conceptual)

```
                    ┌─────────────────────────────────────┐
                    │           Windows Host               │
                    │   (i7-13700KF + RTX 4080 16 GB)     │
                    └─────────────────────────────────────┘
                              │
                    ┌─────────▼───────────────────────────┐
                    │           WSL2 (ext4)                │
                    │         k3s cluster                   │
                    └─────────────────────────────────────┘
                         │  │  │  │  │  │
        ┌────────────────┼──┼──┼──┼──┼──┤               │
        │ namespace      │  │ ollama│monitoring│   ◄─────┘ Istio ingress gateway
        ├────────────────┤  └──┼────┬────┘    │         │ (spec 08)
        │  platform     │    │  │    │      │         │
        │ (GPU plugin)  │    │  │    │      │         │
        ├───────────────┤    │ openviking   │ ◄──┘     LiteLLM gateway
        │     data      │    │             │ (spec 09)
        │ (Postgres +   │    │            hermes│
        │  SOPS age key)│    └────┬──────────┘ (agent)
        ├───────────────┤         │            webui
        │ monitoring    │         │ (spec 05)
        ├───────────────┤     egress
        │ istio-system  │         │
        ├───────────────┤               │
        │ litellm       │               │
        └───────────────┘               │
                                         │
                    ┌────────────────────▼────────────────────┐
                    │            External Access                │
                    │   — GitHub, package registries           │
                    │   — DNS for MCP/browser tools             │
                    │   — LiteLLM egress allowlist              │
                    └──────────────────────────────────────────┘
```

---

## Core Components

### Platform Foundation (Spec 01)

Prepares the Windows 11 + WSL2 host and single-node k3s cluster with:

- GPU passthrough via NVIDIA driver (610.x, CUDA 13.x)
- k3s with containerd, NVIDIA runtime (`nvidia-ctk`), device plugin advertising 1 GPU
- `local-path` StorageClass on WSL ext4 volume (not `/mnt/c`)
- Namespaces: `ollama`, `openviking`, `hermes`, plus later `monitoring`, `istio-system`, `litellm`, `open-webui`
- Helm/Kustomize manifests under `deploy/` for declarative, ordered rollout

### Ollama Inference (Spec 02)

Runs a single Ollama instance in namespace `ollama` as the only local inference endpoint:

- RuntimeClass: `nvidia`, GPU request: `nvidia.com/gpu: 1`
- Models (pinned tags, never `latest`):
  - Chat: `qwen3.5:9b` (thinking enabled), context 65536
  - Embedding: `nomic-embed-text` (resident)
  - VLM: `qwen2.5vl:3b`
- VRAM management: models swap to free the chat/VLM slot; cold-load delay tolerated
- ConfigMap exposes `/v1` API endpoints for LiteLLM
- ClusterIP Service only; no Ingress or NodePort

### OpenViking Context Service (Spec 03)

Runs in namespace `openviking` as a standalone HTTP service:

- Image built from repo Dockerfile (Python 3.1x-slim base), pinned version/commit
- Storage: PVC mounted at data directory on WSL ext4
- Embedding and VLM aliased to LiteLLM endpoint (`litellm.litellm.svc`)
- Non-root user, read-only root filesystem
- ClusterIP Service exposes MCP endpoint if supported
- Istio AuthorizationPolicy allows ingress from Hermes only

### Hermes Agent (Spec 04)

Runs in namespace `hermes`, using the NousResearch/hermes-agent image:

- Image built with pinned version; non-root UID/GID, read-only root filesystem
- ConfigMap delivers config.yaml with LiteLLM endpoint, model alias, context length
- Storage: PVC for `~/.hermes` (sessions, skills) and bounded workspace volume
- Safety boundaries: no cluster credentials, dropped capabilities, resource limits
- Egress restricted to LiteLLM, OpenViking, DNS, and the Squid egress proxy (GitHub, Anthropic and Discord hosts)
- Interactive (`kubectl exec -it`) and headless modes

### LiteLLM Gateway (Spec 09)

Runs in namespace `litellm` as the routing layer for all model calls:

- Official LiteLLM image, pinned tag/digest, ClusterIP Service
- OpenAI-compatible endpoint at `/v1` with stable aliases:
  - `chat`: qwen3.5:9b (thinking on)
  - `embed`: nomic-embed-text
  - `vision`: qwen2.5vl:3b
- Virtual keys (`hermes`, `openviking`, `open-webui`) from SOPS Secrets
- Built-in MCP gateway for tool registration
- Prometheus metrics endpoint; logs without prompt/response by default
- No cloud fallbacks; fails fast on Ollama outage (180 s timeout)

### Istio Service Mesh (Spec 08)

Ambient mode, single ingress gateway:

- mTLS (STRICT), AuthorizationPolicies, default-deny NetworkPolicy, `REGISTRY_ONLY` egress
- Ingress gateway exposes the platform to external clients
- Egress allowlist enforced by the Squid proxy, because `REGISTRY_ONLY` does not block unregistered hosts in ambient mode

### Observability (Spec 06)

- Prometheus Operator with kube-prometheus-stack
- Grafana dashboard
- Metrics exporters: node-exporter, GPU exporter (DCGM not used on WSL2), Postgres
- ServiceMonitors for cluster scraping

### GitOps with Flux (Spec 10)

Flux controllers in `flux-system`:

- source-controller, kustomize-controller, helm-controller only
- Ordered rollout via `dependsOn` chain: platform → data → monitoring → istio → inference → gateway → apps → observability → mesh-policy
- SOPS + age for secret decryption in-cluster; ciphertext committed to public repo
- Pre-commit hook and CI guard block plaintext secrets
- Drift detection, rollback via `git revert`, suspend/resume override

### Nightly Specter Improvement (Spec 11)

Headless cron job that:

- Runs a Specter agent through Hermes to probe/improve the stack nightly
- Commits spec improvements and updates `specs/00-index.md`
- Verified in cluster via proxy; GitHub token for write access

### Haiku via the Claude Code CLI (Spec 12)

- Haiku runs through a wrapper script around the Claude Code CLI in the Hermes pod, on the owner's subscription, with no API key and no API credits.
- The CLI gets no tools. The wrapper caps calls per day, parallel calls, and time.
- It reaches api.anthropic.com only through the Squid egress proxy.
- Its audit log holds no prompt or response text.
- LiteLLM stays local-only and has no Anthropic provider.

### Hermes Swarm Orchestration (Spec 13)

- The swarm engine runs inside the Hermes pod.
- Haiku plans and judges, while local qwen3.5:9b does the bounded steps.
- A script routes each step by its tag and retry count. A model never picks its own tier.
- At most two local calls and a configured number of Haiku calls run at once.
- Only non-LLM verifiers decide that a step succeeded.
- Hard caps (steps, Haiku calls, wall clock) and kill switches (hermes pause and disabled flag files) end a run.

---

## Deploy Layout

```
deploy/
├── platform/     GPU plugin, runtime class, storage
├── ollama/       Inference Deployment, Service, PVCs
├── openviking/   Context service Deployment, ConfigMap, MCP
├── hermes/       Agent Deployment, config.yaml, workspace PV
├── litellm/      Gateway Deployment, Virtual keys, DB Secret
├── open-webui/   Frontend UI
├── monitoring/   Prometheus, Grafana exporters
├── istio/        Ambient mesh, Ingress gateway, AuthorizationPolicies
└── README.md     Bootstrap order and teardown steps

clusters/dsm-shai/flux-system/
└── kustomization.yaml  Flux Kustomizations for GitOps rollout
```

---

## VRAM Budget (16 GB card, estimates in GiB)

| Component                          | Chat + embed (steady state) | VLM + embed (after swap) |
|------------------------------------|-----------------------------|--------------------------|
| Windows/WDDM reserve               | 1.0                         | 1.0                      |
| qwen3.5:9b Q4_K_M weights          | 9.3                         | n/a (evicted)            |
| KV cache @ 64k, q8_0 (~2.7 GiB)    | 2.7                         | n/a                      |
| qwen2.5vl:3b + vision encoder      | n/a                         | 3.2                      |
| VLM KV cache (worst case)          | n/a                         | 0.6                      |
| Compute graph / scratch            | 0.7                         | 0.5                      |
| nomic-embed-text                   | 0.3                         | 0.3                      |
| **Total**                          | **14.0**                    | **5.6**                  |

Chat and VLM swap to stay within the 15 GB hard limit.

---

## Secrets Management (Spec 07)

- SOPS + age for in-cluster decryption; ciphertext committed, plaintext never
- `.agekey` never stored in repo; backed up separately
- Kubernetes Secrets hold virtual keys, DB password; backup/restore tested
- Backup scope includes `flux-system/sops-age` key and PVC data

---

## Acceptance Summary (2026-11-17)

| Spec                             | Status    | Notes                                      |
|----------------------------------|-----------|--------------------------------------------|
| 01 Platform Foundation           | IN PROGRESS | wsl restart test; deploy/README order     |
| 02 Ollama Inference              | DONE      | Amended: qwen3.5:9b, 64K context          |
| 03 OpenViking Context            | PARTIAL   | MCP client check pending                   |
| 04 Hermes Agent                  | PARTIAL   | Browser and LLM MCP out of scope (decided); acceptance boxes to tick |
| 05 Web UI Ingress                | PARTIAL   | Windows/LAN reachability checks            |
| 06 Observability                 | PARTIAL   | Mesh metrics; LAN checks                   |
| 07 Secrets Management            | PARTIAL   | Live/fresh-cluster restore; prune          |
| 08 Istio Service Mesh            | PARTIAL   | Mesh metrics and Grafana dashboard (egress is the Squid proxy) |
| 09 LiteLLM Gateway               | PARTIAL   | MCP registration, consumer integrations    |
| 10 GitOps with Flux              | IN PROGRESS | Secret scan; suspend/resume tests         |
| 11 Nightly Specter Improvement   | PARTIAL   | Built/merged; cron entry; go-live          |

---

## Quick Start

1. Bootstrap host and cluster: `scripts/bootstrap-flux.sh`
2. Apply Flux GitOps from `clusters/dsm-shai/flux-system/` via `kubectl apply -k .`
3. Verify reconciliation order with `flux get kustomizations`
4. Drive Hermes interactively or headless; OpenViking is available for MCP tools

---

## Links

- **Specs catalog:** [`specs/00-index.md`](../specs/00-index.md)
- **Platform constraints:** [`CLAUDE.md`](../CLAUDE.md)
- **Secrets backup/restore:** [`docs/secrets.md`](secrets.md), [`docs/restore.md`](restore.md)
