# Build Task List: Specs 01–10

**Snapshot (2026-11-16):** Steps 1–6 are implemented and reconciled by Flux from `main@0271961`. All six Flux stages (`platform`, `secrets`, `monitoring`, `istio`, `inference`, `flux-system`) report Ready. Steps 7–14 are not started. Legend: `[x]` done, `[~]` partly done (open items listed), `[ ]` not started.

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
  - Done: `scripts/30-verify.sh` passes (host, tooling, cluster, GPU, storage, smoke tests).
  - Open: `wsl --shutdown` restart test (node returns to Ready, GPU smoke test passes); second run of the install scripts confirmed as a no-op; `deploy/README.md` bootstrap order to reflect that Flux now owns `deploy/platform/` (and that `25-platform.sh` skips itself).
  - Depends on: none. Blocks: all.
- [~] **2. Spec 10 — GitOps with Flux.** Bootstrap Flux (source, kustomize and helm controllers only), add in-cluster SOPS decryption, and lay out `clusters/dsm-shai/` with the stage Kustomizations.
  - Done: pinned Flux 2.10.0 components with memory limits at 512Mi; public HTTPS GitRepository with no credential; `scripts/bootstrap-flux.sh` (idempotent); all stage Kustomizations reconciled from `main`.
  - Open: pre-commit and CI secret scanning (gitleaks, plus a check that every `*.sops.yaml` has a `sops:` block); `flux suspend`/`resume` override test; deliberate-break test (bad Istio value blocks downstream); `git revert` rollback test; measured controller memory recorded; `deploy/flux/README.md`; `docs/restore.md`; `REGISTRY_ONLY` egress allow-list for `flux-system` (after spec 08 part B).
  - Depends on: 01. Note: `secrets.yaml` is gitignored, so the stage file is `clusters/dsm-shai/data.yaml`.
- [~] **3. Spec 07 part A — Secrets (SOPS + age).** Create the age key and `.sops.yaml`, encrypt the first Secrets, and confirm Flux decrypts them.
  - Done: age key at `~/.config/sops/age/keys.txt` with an extra copy in `shai-backups`; `.sops.yaml`; `deploy/secrets/grafana-admin.sops.yaml` encrypted; Flux decrypts it (verified in-cluster).
  - Open: offline key backup procedure documented; `scripts/apply-secrets.sh` break-glass tool (fails closed without the key, leaves no plaintext on disk); key-rotation workflow; Open WebUI secret when spec 05 lands.
  - Depends on: 01, 10.
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
  - Depends on: 01, 07 part A. Enrolment in the mesh happens in step 11.
- [ ] **7. Spec 09 — LiteLLM Gateway.** Deploy LiteLLM in the `litellm` namespace with Postgres for virtual keys. Route the `chat`, `embed` and `vision` aliases to Ollama. Add the master key, the MCP and browser tool registrations, and the ServiceMonitor. Issue no consumer keys yet.
  - Depends on: 02, 07 part A, 08 part A, 06 part A.
- [ ] **8. Spec 03 — OpenViking Context Service.** Deploy OpenViking with `ov.conf` pointing at `http://litellm.litellm.svc:4000/v1`. Issue the `openviking` virtual key.
  - Depends on: 01, 07 part A, 09 (cycle broken here).
- [ ] **9. Spec 04 — Hermes Agent.** Deploy Hermes with its `hermes` virtual key, the browser MCP tools, and the OpenViking endpoint.
  - Depends on: 02, 03, 08 part A, 09.
- [ ] **10. Spec 05 — Web UI and Ingress.** Deploy Open WebUI with the `open-webui` virtual key and route it through the ingress gateway (host-local only, per spec 05).
  - Depends on: 07 part A, 08 part A, 09.
- [ ] **11. Spec 08 part B — Mesh enrolment and policy.** Enrol the namespaces in PERMISSIVE mTLS and verify each one. Add ALLOW policies, then default-deny. Switch to STRICT mTLS, with the documented Prometheus scrape exception. Apply REGISTRY_ONLY egress with the Hermes allowlist.
  - Depends on: 03, 04, 05, 06 part A, 09. Each sub-step is its own commit.
- [ ] **12. Spec 06 part B — Observability complete.** Deploy the DCGM exporter (or the nvidia-smi fallback), the Ollama `/api/ps` exporter, the Grafana route through the gateway (host-local), dashboards provisioned from ConfigMaps, and the PrometheusRule alerts. Run the fire tests.
  - Depends on: 02, 08 part A (gateway), 08 part B (scrape exception documented).
- [ ] **13. Spec 07 part B — Backup and restore.** Schedule restic backups, cover Postgres, Grafana, Hermes, OpenViking and Open WebUI data, and run a restore drill. Record the result.
  - Depends on: 03, 04, 05, 06, 08, 09 (the data to protect exists).
- [ ] **14. Index update.** Mark each spec DONE in `specs/00-index.md`, and record the measured footprint and the WSL2 GPU-metric result.
  - Depends on: 1–13.

## Verification gates

After each step, the spec's Acceptance Criteria must pass before the next step starts. Each Flux stage must show Ready in `flux get kustomizations` before dependents apply.

Steps 1–6 were brought up through `kubectl`/`helm` where Flux could not yet sync from GitHub, then handed to Flux once `main` carried the stage files. Steps 2–6 are now reconciled by Flux from `main`.
