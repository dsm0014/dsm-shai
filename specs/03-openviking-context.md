# Spec 03 — OpenViking Context Service

**Status:** PARTIAL (deployed and verified: write/search, restart persistence, LiteLLM attribution; NetworkPolicy/Istio deny and MCP client check pending; see deploy/openviking/README.md)

## Purpose
Run OpenViking as a standalone, cluster-internal HTTP service in the k3s `openviking` namespace. It gives Hermes Agent (spec 04) persistent memory, resources, and skills through the `viking://` filesystem paradigm. All model calls go through the in-cluster LiteLLM gateway (spec 09) to Ollama (spec 02), so no cloud provider is needed.

## Behavior
- **Dependencies:** Spec 01 provides the k3s cluster and the `openviking` namespace. Spec 09 provides the LiteLLM gateway at `http://litellm.litellm.svc:4000/v1`, which fronts Ollama from spec 02.
- **Image:** OpenViking may not publish an official image, so the repo builds one from a `Dockerfile` kept in `deploy/openviking/`.
  - Base image is a digest-pinned `python:3.1x-slim`, because OpenViking needs Python 3.10+.
  - `uv` installs `openviking` pinned to an exact released version, or to a git commit SHA of `volcengine/OpenViking` if no release fits. The pin is recorded in the Dockerfile and the manifests.
  - The image runs as a non-root user, and its entrypoint starts the OpenViking HTTP server on a fixed port.
  - Before the Dockerfile is finalized, confirm the server command, port, config path, and data path against the pinned version. If an official image exists, pin it by digest and skip the build.
  - The image is built locally and imported into k3s containerd, or pushed to a local registry. Manifests reference an immutable tag or digest and never use `latest`.
- **Config:** A ConfigMap holds the OpenViking config file and is mounted read-only at the path the pinned version expects.
  - Embedding is the `embed` alias (nomic-embed-text) through the OpenAI-compatible provider at `http://litellm.litellm.svc:4000/v1`, with the embedding dimension set to match (768).
  - The VLM is the `vision` alias (qwen2.5vl:3b) at the same endpoint.
  - Authentication uses the `openviking` LiteLLM virtual key (spec 09), delivered as a SOPS-managed Secret (spec 07).
  - Config changes roll out by restarting the Deployment, for example with a config-hash annotation.
- **Storage:** A PVC mounted at the OpenViking data directory holds all memory, resources, and skills. No external database is deployed.
  - It uses the k3s `local-path` StorageClass, backed by the WSL ext4 volume (for example under `/var/lib/rancher/k3s/storage`). It is never backed by `/mnt/c`, because the DrvFs path is slow and breaks file semantics.
  - The size is stated in the manifest, with a default of 10Gi.
  - The Deployment has `replicas: 1` and `strategy: Recreate`, because storage is single-writer and I/O bound.
- **Service:** A ClusterIP Service exposes the HTTP port as `openviking.openviking.svc:<port>`.
  - There is no Ingress, NodePort, or LoadBalancer.
  - Istio AuthorizationPolicies (spec 08) allow ingress only from the `hermes` ServiceAccount (spec 04) and egress only to DNS and LiteLLM. A default-deny NetworkPolicy remains as a baseline.
  - The MCP endpoint is exposed on the same Service if the pinned version supports it, so LiteLLM's MCP gateway (spec 09) can register it and expose it to Hermes.
- **Probes and resources:** Startup, readiness, and liveness probes hit the OpenViking health endpoint, or a TCP check on the port if none exists. Requests and limits are set, and the container does not run as root.
- **Manifests:** Plain YAML (ConfigMap, PVC, Deployment, Service, NetworkPolicy) lives in `deploy/openviking/`. `kubectl apply -f` is idempotent.

## Acceptance Criteria
- [x] The image builds reproducibly from the repo, and the base image digest and OpenViking version or commit are pinned in the Dockerfile.
- [x] The image is available to k3s, and the Deployment references it by pinned tag or digest, with no `latest`.
- [x] `kubectl -n openviking apply -f deploy/openviking/` succeeds, and the pod reaches `Ready` with all probes passing.
- [x] The ConfigMap-mounted config names the `embed` and `vision` aliases against `http://litellm.litellm.svc:4000/v1`, and no cloud provider URLs or direct Ollama URLs appear anywhere.
- [x] The PVC is `Bound` on the WSL ext4 `local-path` storage and is mounted at the data directory.
- [ ] The Service is ClusterIP only. A request from outside the cluster fails, and a request from a pod in the Hermes namespace succeeds.
- [x] From a pod in the cluster, a test writes a memory item under `viking://` (with a unique marker string) through the HTTP API, and a retrieval or semantic search returns that item.
- [x] After `kubectl -n openviking rollout restart deployment/openviking`, the same marker item is still retrievable, which shows the data persists across pod restarts.
- [x] LiteLLM metrics (spec 09) show embedding and VLM requests attributed to the `openviking` key during verification.
- [ ] If MCP is supported by the pinned version, an MCP client in the cluster can list tools from the service.
- [x] `deploy/openviking/README.md` documents the build, pin-bump, deploy, and verification steps, and states which spec 01 and spec 02 outputs it relies on.
