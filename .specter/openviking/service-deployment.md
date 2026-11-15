# OpenViking: Server, Config, Auth, Storage and Helm Chart

**Tags:** openviking, deployment, helm, auth, storage, k3s, spec-03

Source: github.com/volcengine/OpenViking (README, `docs/en/guides/*`, Dockerfile, `deploy/helm/openviking`, source at `main`, roughly the 0.3.x line). Licence: AGPLv3 (the `ov` CLI is Apache-2.0), so check this fits the intended use.

## What it is

A context database for agents exposing a virtual filesystem under `viking://` (`resources/`, `user/{id}/{memories,resources,skills,peers}`, `agent/skills`). Each item has three tiers: L0 abstract, L1 overview, L2 full content. The VLM generates L0/L1 and the embedding model vectorises content. A Python HTTP server (`openviking-server`) serves REST, MCP and Web Studio (`/studio`) on **one port, 1933**.

## Config

- JSON file `ov.conf`, default `~/.openviking/ov.conf`, overridden by `OPENVIKING_CONFIG_FILE` (CLI client config: `OPENVIKING_CLI_CONFIG_FILE`). Read once at startup, so changes need a restart. `${VAR}` expansion in values is supported, so keys can be injected from Secrets.
- Minimal shape: `storage.workspace`, `embedding.dense{provider,api_base,api_key,model,dimension}`, `vlm{provider,api_base,api_key,model}`. Many optional sections (`memory`, `query_planner`, `rerank`, `retrieval`, `log`, `encryption`, `oauth`, `gateway`).
- `openviking-server init` is an interactive wizard (needs a TTY), so write the file yourself for Kubernetes. `openviking-server doctor` validates config, model access and auth non-interactively (`kubectl exec`).
- If no `ov.conf` exists in the container, the entrypoint serves a 503 `pending_initialization` until it appears. `OPENVIKING_CONF_CONTENT` can inject the full JSON when the file is missing.

## Auth

- `server.root_api_key` non-empty switches to `api_key` mode. Empty means `dev` mode, which is localhost-only and **refuses to start when bound to a non-loopback address**. A pod binding `0.0.0.0` therefore must have a root key (inject it from a Secret).
- Send keys as `X-API-Key: <key>` or `Authorization: Bearer <key>`. The root key is admin-only. Data access needs a user or admin key created through `POST /api/v1/admin/accounts` and `.../accounts/<id>/users`. A root key used on data endpoints is rejected.
- Other modes: `trusted`, `oidc`, `ldap`. `server.account_store` defaults to a JSON file in the workspace (`mysql`, `postgres` and `redis_mysql` are optional).

## Health endpoints (for probes)

- `GET /health` is unauthenticated and process-level only (use for liveness).
- `GET /ready` checks `agfs`, `vectordb`, `api_key_manager`, `embedding` and an `ollama` probe, returning 503 if a check fails. **An unreachable Ollama endpoint makes `/ready` fail**, so the pod stays unready until Ollama is up. `not_configured` counts as OK.
- Under the mesh, a LiteLLM-fronted setup does not trigger the Ollama probe, because the probe keys off an `ollama` provider or an `ollama/` model prefix and `api_base`. Verify which path applies after pointing OpenViking at LiteLLM.

## Storage

- `storage.workspace` (default `./data`) holds the embedded vector DB, the filesystem backend (`agfs.backend: local`), queue SQLite (`_system/queue/queue.db`), and task and watch stores.
- The local vector DB takes an exclusive `.openviking.lock`, so it is **single-process: one replica, one worker**. Remote vector backends (`http`, `pgvector`, and others) exist but are out of scope here.
- SQLite needs a filesystem with proper locking, so keep the PVC on the WSL ext4 `local-path` volume (not `/mnt/c`).
- Docker layout: `HOME=/app`, working dir `/app/.openviking`, containing `ov.conf`, `ovcli.conf` and `data/`. Mount one volume there. Older images wrote `/app/data` outside the mount, so back that up before replacing the container.
- Backup tools in the docs: snapshots and ovpack export. Prefer a stopped or quiesced copy of the PVC with restic (spec 07), because the vector DB is not safe to copy while running.

## Container and Helm chart

- Image: `ghcr.io/volcengine/openviking:<tag>` (pin tag and digest, not `latest`). Entry point binds `0.0.0.0` by default. `EXPOSE 1933`.
- VikingBot starts by default (`OPENVIKING_WITH_BOT=1`). **Disable it** with `OPENVIKING_WITH_BOT=0` or `--without-bot`.
- Chart `deploy/helm/openviking`: needs K8s 1.24+ and an RWO StorageClass (`local-path` works). It forces `replicaCount: 1` with `strategy: Recreate`. `.Values.config` renders into a read-only ConfigMap mounted at `/app/.openviking/ov.conf`. A PVC `<fullname>-data` (20Gi default, annotated `helm.sh/resource-policy: keep`) is mounted at `/app/.openviking`.
- Probes: liveness `GET /health` (30s delay), readiness `GET /ready` (15s delay, 10s period). Default resources: requests 500m CPU / 1Gi, limits 2 CPU / 4Gi. Service type ClusterIP on 1933.
- Secrets: put `"${OPENVIKING_ROOT_API_KEY}"` in `config` and supply the value via `extraEnv` + `secretKeyRef`.
- The chart's default `config` is Volcengine-based. Override `embedding` and `vlm` fully, and set `embedding.dense.input: text` explicitly, because leftover `multimodal` defaults would break a text-only embedding model. Check the result with `helm template`.
- If the repo's chart is not used directly, vendor or render it into `deploy/openviking/` with pinned values.

## Notes for dsm-shai

- OpenViking is a mesh member behind LiteLLM (spec 09) for models and may expose its own MCP endpoint (see [[openviking-ollama-models-and-mcp]]).
- If reverse-proxied or ingress-exposed, set `OPENVIKING_PUBLIC_BASE_URL` (or `server.public_base_url`), and forward `/api/v1/*` as well as `/mcp`, with request buffering off and long read timeouts (600s). In this design access stays cluster-internal.
