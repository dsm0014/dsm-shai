# Spec 03 — OpenViking Context Service

**Status:** TODO

## Purpose
Run OpenViking as a standalone, cluster-internal HTTP service in the k3s `openviking` namespace. It gives Hermes Agent (spec 04) persistent memory, resources, and skills through the `viking://` filesystem paradigm. All model calls go through the in-cluster LiteLLM gateway (spec 09) to Ollama (spec 02), so no cloud provider is needed.

## Behavior
- **Dependencies:** Spec 01 provides the k3s cluster and the `openviking` namespace. Spec 09 provides the LiteLLM gateway at `http://litellm.litellm.svc:4000/v1`, which fronts Ollama from spec 02.
- **Image:** OpenViking publishes `ghcr.io/volcengine/openviking:<tag>`, so the repo does not build one. The image is pinned by tag and digest, never `latest`, and the pin is recorded in the manifests.
  - Set `OPENVIKING_WITH_BOT=0` to disable VikingBot, which starts by default.
  - The upstream Helm chart (`deploy/helm/openviking`) may be vendored or rendered into `deploy/openviking/` with pinned values. Check the result with `helm template`. Its default config is Volcengine-based, so `embedding` and `vlm` are overridden fully and `embedding.dense.input: text` is set explicitly.
  - OpenViking is AGPLv3 (the `ov` CLI is Apache-2.0). The repo is public and the service is internal only, but the licence is noted in the README.
- **Config:** `ov.conf` (JSON) is delivered by a ConfigMap, mounted read-only at `/app/.openviking/ov.conf` (or pointed to by `OPENVIKING_CONFIG_FILE`). It is read once at startup, so changes roll out by restarting the Deployment, for example with a config-hash annotation. `${VAR}` expansion injects keys from Secrets.
  - Embedding is the `embed` alias (nomic-embed-text) through an OpenAI-compatible provider at `http://litellm.litellm.svc:4000/v1` (the `api_base` includes `/v1`). The `dimension` is set to 768 and locked before the first ingest, because changing it later requires a full reindex.
  - The VLM is the `vision` alias (qwen2.5vl:3b) at the same endpoint. It is not optional, because summaries and overviews come out empty without it. `vlm.timeout` is raised above the cold model-swap time (chat and vision are not co-resident in VRAM).
  - The memory-extraction prompt is about 5k tokens. Verify that LiteLLM forwards `extra_request_body` (`num_ctx`, `think: false`) to Ollama, or rely on the 32k server default context from spec 02.
  - Authentication: `server.root_api_key` is mandatory because the pod binds `0.0.0.0` (without it the server refuses to start). It comes from a SOPS-managed Secret (spec 07). The root key is admin-only, so a separate account and user key is created through the admin API for the LiteLLM MCP registration (see Service below).
  - The `openviking` LiteLLM virtual key (spec 09) is delivered as a SOPS-managed Secret.
- **Storage:** A PVC mounted at `/app/.openviking` (config plus `data/`) holds all memory, resources, and skills. No external database is deployed.
  - The embedded vector DB takes an exclusive lock, so it is single-process: one replica and one worker. `replicas: 1` and `strategy: Recreate` are mandatory, not just preferred.
  - It uses the k3s `local-path` StorageClass, backed by the WSL ext4 volume (for example under `/var/lib/rancher/k3s/storage`). It is never backed by `/mnt/c`, because SQLite needs proper locking and DrvFs breaks file semantics.
  - The size is stated in the manifest, with a default of 10Gi. The PVC is annotated `helm.sh/resource-policy: keep` and is prune-exempt under Flux (spec 10).
  - Backups use a quiesced or stopped copy of the PVC (spec 07), because the vector DB is not safe to copy while running.
- **Service:** A ClusterIP Service exposes the HTTP port as `openviking.openviking.svc:<port>`.
  - There is no Ingress, NodePort, or LoadBalancer.
  - Istio AuthorizationPolicies (spec 08) allow ingress only from the `hermes` ServiceAccount (spec 04) and egress only to DNS and LiteLLM. A default-deny NetworkPolicy remains as a baseline.
  - OpenViking serves Streamable HTTP MCP at `/mcp` on the same port (1933), so LiteLLM's MCP gateway (spec 09) registers `http://openviking.openviking.svc:1933/mcp` with a bearer token for an OpenViking **user** key (not the root key) and exposes only the needed tools (read/search, plus `remember` if Hermes should write memory) to Hermes.
- **Probes and resources:** Liveness is `GET /health` (unauthenticated, process-level). Readiness is `GET /ready`, which checks the vector DB, embedding and an Ollama probe and returns 503 if one fails, so the pod stays unready until its model backend is reachable. Verify which probe path applies once the config points at LiteLLM rather than Ollama. Requests and limits are set (chart defaults 500m/1Gi requests, 2 CPU/4Gi limits), and the container does not run as root.
- **Manifests:** Plain YAML or a vendored chart (ConfigMap, PVC, Deployment, Service, NetworkPolicy) lives in `deploy/openviking/` and is reconciled by Flux (spec 10). `openviking-server doctor` (via `kubectl exec`) validates config, model access and auth.

## Acceptance Criteria
- [ ] The Deployment references `ghcr.io/volcengine/openviking` by pinned tag and digest, with no `latest`, and VikingBot is disabled.
- [ ] The `deploy/openviking/` manifests reconcile cleanly under Flux, and the pod reaches `Ready` with `/health` and `/ready` passing. `openviking-server doctor` reports healthy.
- [ ] The server refuses to run without `root_api_key` (verified once in a throwaway run), and the key comes from a Secret.
- [ ] The embedding `dimension` is 768 in config before first ingest, and the README records that changing it requires a reindex.
- [ ] The ConfigMap-mounted config names the `embed` and `vision` aliases against `http://litellm.litellm.svc:4000/v1`, and no cloud provider URLs or direct Ollama URLs appear anywhere.
- [ ] The PVC is `Bound` on the WSL ext4 `local-path` storage and is mounted at the data directory.
- [ ] The Service is ClusterIP only. A request from outside the cluster fails, and a request from a pod in the Hermes namespace succeeds.
- [ ] From a pod in the cluster, a test writes a memory item under `viking://` (with a unique marker string) through the HTTP API, and a retrieval or semantic search returns that item.
- [ ] After `kubectl -n openviking rollout restart deployment/openviking`, the same marker item is still retrievable, which shows the data persists across pod restarts.
- [ ] LiteLLM metrics (spec 09) show embedding and VLM requests attributed to the `openviking` key during verification.
- [ ] An MCP client authenticated with an OpenViking user key can list tools at `/mcp`, and LiteLLM's MCP gateway exposes them to the `hermes` key only. The root key is rejected on data endpoints.
- [ ] `deploy/openviking/README.md` documents the pin-bump, deploy, account and user-key creation, and verification steps, and states which spec 01 and spec 02 outputs it relies on.
