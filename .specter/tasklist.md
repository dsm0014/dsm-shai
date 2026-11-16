# Build Task List: Specs 01–10

**Snapshot (2026-11-16):** Steps 1–14 are implemented. All 13 Flux stages (including `litellm`, `openviking`, `hermes`, `open-webui`, `mesh-policies`, `gpu-exporter`, `monitoring-extras`) report Ready from `main@db4986c` (PR #9). Items still marked open need you or were decided out of scope. Legend: `[x]` done, `[~]` partly done (open items listed), `[ ]` not started.

Specs 07, 08 and 06 are split into phases, because their rollout requires the workloads they protect or observe to exist first. Spec 10 delivers everything in-cluster, so its bootstrap comes early.

## Ordering rules

- Spec 01 blocks everything.
- Spec 10 (Flux, SOPS) comes before any workload, because later specs are delivered through it.
- Spec 07 part A (SOPS wiring) comes before any spec that consumes a Secret.
- Spec 06 part A (Prometheus Operator CRDs) comes before any ServiceMonitor or PodMonitor is applied (istio, litellm, DCGM).
- Spec 08 part A (install) comes before workloads. Spec 08 part B (namespace enrolment, policies, STRICT mTLS, egress) comes after the workloads it protects.
- **Cycle 03 ↔ 09 broken explicitly:** LiteLLM (09) is deployed before OpenViking, Hermes and Open WebUI. Each consumer's virtual key is issued when that consumer is deployed.

## Task list

- [~] **1. Spec 01 — Platform Foundation.** Set `.wslconfig` to 24GB, install k3s with Traefik disabled, configure the NVIDIA runtime and GPU plugin, create the namespaces, and set up the storage class on ext4.
  - Done: `scripts/30-verify.sh` passes; `deploy/README.md` bootstrap says Flux owns `deploy/platform/`, and `25-platform.sh` skips itself; `.wslconfig` (24GB) is applied (WSL shows 23 GiB).
  - Open (needs you, not runnable from this session): the `wsl --shutdown` restart test (it stops this session and the whole stack); the second run of the install scripts as a no-op (needs sudo).

- [x] **2. Spec 10 — GitOps with Flux.** Bootstrap Flux (source, kustomize and helm controllers only), add in-cluster SOPS decryption, and lay out `clusters/dsm-shai/` with the stage Kustomizations.
  - Done: pinned Flux 2.10.0; public GitRepository; `scripts/bootstrap-flux.sh`; stage Kustomizations; PR #7 merged to `main` (8934b4b) and all stages reconciled from it (platform resumed; all stages Ready); pre-commit secret scan; suspend/resume test; deliberate-break and `git revert` tests on a throwaway branch; controller memory recorded; `deploy/flux/README.md`; `docs/restore.md`.
  - Decided by you: the CI secret scan stays inactive (the `workflow` token scope is not added); the workflow file is in `ci/`.
  - Depends on: 01. Note: `secrets.yaml` is gitignored, so the stage file is `clusters/dsm-shai/data.yaml`.
- [x] **3. Spec 07 part A — Secrets (SOPS + age).** Create the age key and `.sops.yaml`, encrypt the first Secrets, and confirm Flux decrypts them.
  - Done: age key at `~/.config/sops/age/keys.txt`, with an offline copy in `shai-backups` and the restic backup; `.sops.yaml`; encrypted Secrets for Grafana, LiteLLM, OpenViking, Hermes and Open WebUI; `scripts/apply-secrets.sh` break-glass (refuses without the key, leaves no plaintext, tested); the key-rotation and offline-backup workflow in `docs/secrets.md` and `docs/restore.md`; the Open WebUI secret is in place.

- [x] **4. Spec 06 part A — Observability base.** Deploy the kube-prometheus-stack HelmRelease: Prometheus Operator, Prometheus with retention and PVC, Grafana with its admin Secret, node-exporter and kube-state-metrics. Alertmanager and control-plane scrapes are disabled.
  - Done: kube-prometheus-stack 93.3.0 Ready under Flux; Grafana reads `grafana-admin`; CRDs present; Prometheus PVC 30Gi, Grafana PVC 5Gi.
  - Deviation: node-exporter root-filesystem mount is disabled (WSL2 root mount is not shared; `mount --make-rshared /` needs root). Other node metrics are collected.
  - Depends on: 01, 07 part A, 10. Blocks: the ServiceMonitors in steps 5, 7 and 12.
- [x] **5. Spec 08 part A — Istio install.** Install istio-base, istio-cni, istiod, ztunnel and the ingress gateway, in that order, with Flux `dependsOn` chains. No namespace enrolment yet.
  - Done: all five releases (1.30.8) Ready in `istio-system`, pods Running, 15 Istio CRDs. Ingress gateway is ClusterIP (host-local; spec 05 publishes it).
  - Depends on: 01, 10, 06 part A (for Istio's ServiceMonitor, not yet added).
- [x] **6. Spec 02 — Ollama Inference.** Deploy Ollama with the VRAM budget, keep-alive and model pulls (chat, embed, VLM). Verify that models swap within the 16GB budget.
  - Done: Ollama 0.40.16 on the RTX 4080; three models on a 50Gi PVC; preload Job idempotent on rerun; API checks pass (`/v1/models`, `/v1/embeddings`, tool calls, vision); 28,843-token prompt at 32k context fully on GPU; VLM and chat swap with embed resident and no OOM; embed pinned by `ollama-embed-pin` CronJob. Measured values in `deploy/ollama/README.md`.
  - Open (moved to other steps): `/v1/models` from the `litellm` namespace (step 7); "not reachable from outside the cluster" denial check (step 11, spec 08 part B).
  - Amended 2026-11-16: chat model is now `qwen3.5:9b` at a 64K context (Hermes requires 64K; PR #9). It replaced `llama3.1:8b`, whose Ollama template forces a tool call on every turn. It needs thinking on. Measurements are in `deploy/ollama/README.md`. The qwen3 figures above are the earlier baseline.
  - Depends on: 01, 07 part A. Enrolment in the mesh happens in step 11.
- [~] **7. Spec 09 — LiteLLM Gateway.** Deploy LiteLLM in the `litellm` namespace with Postgres for virtual keys. Route the `chat`, `embed` and `vision` aliases to Ollama. Add the master key, the MCP and browser tool registrations, and the ServiceMonitor. Issue no consumer keys yet.
  - Done: LiteLLM 1.109.1 (pinned by digest) and Postgres 16; `chat`, `embed`, `vision` verified (streaming, tool calls, vision, embeddings); 401 for missing or wrong keys; per-key model allowlist (403 outside it); concurrency limit; ServiceMonitor scraped; no prompt logging; SOPS-encrypted secrets; the MCP gateway has the OpenViking server registered with a server tool allowlist, a per-key MCP allowlist (the `hermes` key gets 403 until granted), and tools list with status `ok`.
  - Open: browser MCP registration (skipped by your decision); 'fails fast' when Ollama is down is not met (the outage is bounded by the 180 s timeout; see `deploy/litellm/README.md`).

- [x] **8. Spec 03 — OpenViking Context Service.** Deploy OpenViking with `ov.conf` pointing at `http://litellm.litellm.svc:4000/v1`. Issue the `openviking` virtual key.
  - Done: upstream image pinned by digest; UID 1000; `/health` and `/ready` pass; `embed` and `vision` through LiteLLM with the `openviking` key; write and semantic search verified; the marker survives a restart; LiteLLM attributes calls to `openviking`; the MCP endpoint lists 27 tools to a client in the cluster (Hermes); NetworkPolicy and Istio ingress limited to Hermes (and the LiteLLM gateway identity).

- [~] **9. Spec 04 — Hermes Agent.** Deploy Hermes with its `hermes` virtual key, the browser MCP tools, and the OpenViking endpoint.
  - Done: upstream image `v0.23.1` pinned by digest (not built here); non-root (UID 10000, no s6 init); `hermes` virtual key (chat only); headless gateway; `/opt/data` persists across pod replacement; end-to-end task with an explicit tool instruction; memory written to OpenViking and recalled by a fresh session (direct MCP route); egress default-deny by NetworkPolicy; the chat model is `qwen3.5:9b` at 64K with thinking on (PR #9; `coding_context` off).
  - Open: the browser MCP tools (skipped by your decision); the hostname egress allowlist (kept as default-deny by your decision, so the spec's allowlist is not met); Hermes does not route OpenViking through the LiteLLM gateway (a tool-surface problem with the 8B model; see `deploy/hermes/README.md`); `readOnlyRootFilesystem` not tested. The Flux stage is done (PR #8, Ready).

- [~] **10. Spec 05 — Web UI and Ingress.** Deploy Open WebUI with the `open-webui` virtual key and route it through the ingress gateway (host-local only, per spec 05).
  - Done: Open WebUI v0.13.3 (pinned by digest) as UID 1000; LiteLLM backend with the `open-webui` key (`chat`, `vision`); `ENABLE_SIGNUP=False` (first admin, then 403); SearXNG skipped; PVC persists; Istio `Gateway` and `VirtualService` for `open-webui.localhost`; login, sign-in, models and a chat completion verified through the ingress; NetworkPolicy egress limited to DNS, LiteLLM and the mesh tunnel (verified: public internet, direct Ollama and direct OpenViking refused).
  - Open (needs you): the LAN-unreachable check from a second device; the Windows browser check. The Flux stage is done (Ready).

- [~] **11. Spec 08 part B — Mesh enrolment and policy.** Enrol the namespaces in PERMISSIVE mTLS and verify each one. Add ALLOW policies, then default-deny. Switch to STRICT mTLS, with the documented Prometheus scrape exception. Apply REGISTRY_ONLY egress with the Hermes allowlist.
  - Done: six namespaces enrolled in ambient; identity ALLOW policies with a deny-all baseline; mesh-wide STRICT mTLS; PERMISSIVE and STRICT rollback drill passed; allowed and denied paths verified; Hermes egress default-deny by NetworkPolicy; mesh memory about 250 Mi; a namespace-label incident (Flux stripped the labels) is recorded in `deploy/istio/README.md`.
  - Open: the hostname egress allowlist (`REGISTRY_ONLY` does not block unregistered hosts in ambient; the NetworkPolicy is IP-only; kept as default-deny by your decision); Kiali not checked (off by default; its 'works when enabled' check not run). The mesh-policies stage is done (Ready). After a `wsl --shutdown`, pods that were already running need deleting so ztunnel re-enrols them (see `deploy/istio/README.md`); `postgres-0` needed this on 2026-11-16.

- [~] **12. Spec 06 part B — Observability complete.** Deploy the DCGM exporter (or the nvidia-smi fallback), the Ollama `/api/ps` exporter, the Grafana route through the gateway (host-local), dashboards provisioned from ConfigMaps, and the PrometheusRule alerts. Run the fire tests.
  - Done: nvidia-smi exporter (DCGM not in the image) with Ollama `/api/ps` loaded-model metrics; GPU memory agrees with host nvidia-smi; three dashboards from ConfigMaps (GPU and Ollama; workloads and node; service mesh); seven alert rules; fire tests firing for VRAM, crash loop and PVC; Prometheus data survives a restart; 15d retention and 20GiB size limit live; no Alertmanager; control-plane scrapes absent; istiod and ztunnel metrics scraped; Grafana through the host-local ingress returns 200; footprint about 1.15 GiB.
  - Open (needs you): the LAN-unreachable check from a second device; the Windows browser check. The Flux stage is done (Ready).

- [~] **13. Spec 07 part B — Backup and restore.** Schedule restic backups, cover Postgres, Grafana, Hermes, OpenViking and Open WebUI data, and run a restore drill. Record the result.
  - Done: restic 0.19.1 (checksum verified) with an encrypted repository on the Windows drive, outside the WSL disk; `scripts/backup.sh` quiesces each app and streams its PVC, `pg_dump` for LiteLLM Postgres, Istio CA, `sops-age` and the age key; retention `7 daily, 4 weekly, 3 monthly` with prune and a free-space floor; daily systemd user timer with linger, and a run through systemd succeeded; the restore drill (2026-11-16) restored every tag to a staging folder and a scratch Postgres, and the age key decrypted a live Secret; the repo refuses reads without the password.
  - Open: a live restore over running PVCs and a fresh-cluster restore (not run: destructive, or needs a second install); the k3s datastore snapshot (needs root); `wsl --export` not run; prune not yet observed (needs about eight days of snapshots).

- [x] **14. Index update.** Mark each spec DONE in `specs/00-index.md`, and record the measured footprint and the WSL2 GPU-metric result.
  - Done: `specs/00-index.md` shows each spec's real status (DONE for 02 and 03; PARTIAL or IN PROGRESS for the rest, with the open items listed); measured footprint and WSL2 GPU-metric results recorded. Specs 04 to 10 are not DONE: each has open items (see the table).
  - Depends on: 1 to 13.

## Verification gates

After each step, the spec's Acceptance Criteria must pass before the next step starts. Each Flux stage must show Ready in `flux get kustomizations` before dependents apply.

Steps 1–6 were brought up through `kubectl`/`helm` where Flux could not yet sync from GitHub, then handed to Flux once `main` carried the stage files. Steps 2–6 are now reconciled by Flux from `main`.
