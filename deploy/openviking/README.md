# deploy/openviking

OpenViking context service (spec 03). Namespace `openviking`. ClusterIP `openviking.openviking.svc:1933`.

## Image

`ghcr.io/volcengine/openviking:v0.5.5@sha256:d0d6d5c2dad366b81d970caf420ce186723e539ffc781b80620298675ea5accc`

The upstream project publishes this image, so the repo does not build one (spec 03 says to pin an official image and skip the build). Bump by changing the tag and the digest together, then checking `/health`, `/ready` and the verification steps below.

## Config

`ov.conf` (ConfigMap `openviking-config`, mounted at `/etc/openviking`, selected with `OPENVIKING_CONFIG_FILE`):

- `embedding.dense`: provider `openai` at `http://litellm.litellm.svc:4000/v1`, model alias `embed`, dimension 768.
- `vlm`: provider `openai` at the same endpoint, model alias `vision`, `max_retries: 0`.
- `server.root_api_key` and the LiteLLM key come from `${...}` placeholders, filled from the SOPS Secret `openviking-secrets`.

No cloud provider and no direct Ollama URL appear anywhere in the config.

## Secrets (SOPS, `deploy/secrets/openviking.sops.yaml`)

| Key | Use |
|---|---|
| `litellm-key` | LiteLLM virtual key `openviking`, allowlist `embed` and `vision`, budget 20, 120 rpm |
| `root-api-key` | OpenViking root key. Required because the server binds `0.0.0.0`. Root keys cannot reach tenant data APIs in `api_key` mode. |
| `verify-user-key` | User key of the verification account `verify` (verification only; revoke when no longer needed) |

Rotate a LiteLLM key with `/key/generate`, then re-encrypt the Secret through `sops --encrypt` from stdin. Never write the plaintext to disk.

## Storage

PVC `openviking-data` (10Gi, `local-path`, on the WSL ext4 volume) mounted at `/app/.openviking`. Single writer, `Recreate` strategy.

## Security

Runs as UID 1000 with `runAsNonRoot`, `RuntimeDefault` seccomp, no privilege escalation, all capabilities dropped, no ServiceAccount token. The upstream image has no `USER` directive, and the service starts without root.

Not yet applied: a read-only root filesystem (the app writes to its own tree), and the NetworkPolicy and Istio authorization that restrict callers to `hermes` (spec 08 part B, step 11).

## Verification (done)

- `/health` and `/ready` return 200. Startup logs show MCP endpoint ready with 27 tools.
- Write a memory with a marker through `POST /api/v1/content/write` (`wait: true`), then find it with `POST /api/v1/search/find`. Result: hit contains the marker.
- `kubectl -n openviking rollout restart deployment/openviking`, then the same search: marker still retrievable.
- LiteLLM metrics attribute `embed` and `vision` requests to key alias `openviking`.

Repeat with: write through the verify key, then `search/find` (root keys are rejected with 403 by design).

## Not yet verified

- Request from outside the cluster is refused: pending the NetworkPolicy and Istio policy (step 11).
- MCP client listing tools from another pod: pending the LiteLLM MCP registration (step 7 remainder).

## Creating a tenant

```sh
# root key stays inside the pod; the returned user_key is shown once
curl -s -H "X-API-Key: $ROOT" -H 'Content-Type: application/json' \
  http://openviking.openviking.svc:1933/api/v1/admin/accounts \
  -d '{"account_id":"<name>","admin_user_id":"<user>"}'
```
