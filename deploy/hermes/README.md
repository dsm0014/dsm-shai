# deploy/hermes

Hermes Agent (spec 04), namespace `hermes`. Status: **running headless, non-root, with a working end-to-end task and OpenViking memory**. Open items at the end.

## Image

`docker.io/nousresearch/hermes-agent:v0.23.1@sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08`

Deviation from spec 04: the spec asks for a build from `deploy/hermes/`. This cluster has no container build daemon (no Docker daemon, no root for `k3s ctr`). The upstream project publishes this image on each release, so it is pinned by digest. Bump the tag and digest together.

## Pod

- Runs as `hermes` (UID 10000) with `runAsNonRoot`, `RuntimeDefault` seccomp, no privilege escalation, all capabilities dropped. The upstream s6 init (root PID 1) is bypassed: the command is `/opt/hermes/docker/main-wrapper.sh gateway run`. An init container has already set ownership and seeded config.
- Headless: the long-lived foreground gateway. `hermes -z "..."` (one-shot) and `hermes chat` both use it.
- `/opt/data` (`HERMES_HOME`) is PVC `hermes-home` (10Gi, `local-path`, WSL ext4). Persistence verified across a pod replacement. The image uses `/opt/data`, not `~/.hermes`.
- `/workspace` is an `emptyDir` with `sizeLimit: 10Gi`.
- ServiceAccount `hermes`, `automountServiceAccountToken: false`. No token directory in the pod. No RBAC.
- No `hostPath`, no Docker or containerd socket. Requests 500m/2Gi, limits 2/4Gi.

## Config (`config.yaml`, ConfigMap `hermes-config`)

Copied to `/opt/data/config.yaml` by the init container on every start. The ConfigMap is the source of truth.

- `model`: `provider: custom`, `base_url: http://litellm.litellm.svc:4000/v1`, `default: chat`, `context_length: 65536` (must equal `OLLAMA_CONTEXT_LENGTH`; Hermes's floor is 64K), `key_env: LITELLM_HERMES_KEY`.
- `agent.reasoning_effort: none`: `llama3.1:8b` has no thinking mode, and Ollama rejects a `think` parameter.
- `agent.disabled_toolsets: [memory]`: OpenViking is the only memory backend.
- `mcp_servers.openviking`: `http://openviking.openviking.svc:1933/mcp`, header `X-API-Key: ${OPENVIKING_KEY}` (tenant key for account `hermes`).

Secrets (SOPS, `deploy/secrets/hermes.sops.yaml`): `litellm-key` (virtual key `hermes`, allowlist `chat`, budget 20, 60 rpm) and `openviking-key` (tenant user key). Both enter the pod as env vars.

## Verification (done, 2026-11-16)

| Check | Result |
|---|---|
| One-shot prompt through LiteLLM to `chat` (`llama3.1:8b`) | `PONG` |
| End-to-end task with explicit terminal instruction: list the 3 largest files in `/workspace/data`, write `/workspace/largest.txt` | file written with `huge.bin`, `big.bin`, `mid.bin` (correct) |
| Memory write: `mcp__openviking__remember` with a two-message submission | extracted into `viking://user/hermes/memories/profile.md` |
| Same memory checked from outside the Hermes pod (OpenViking search with the tenant key) | found |
| Fresh Hermes process recalls the stored code via `mcp__openviking__search` | recalled (the abstract of `profile.md` contains the fact) |
| Pod replacement keeps `/opt/data` | file preserved |
| No cluster credentials in the pod | no token directory |

## Limits (llama3.1:8b, observed)

- **Planning and tool use need explicit instructions.** Without an explicit tool instruction, the model stopped after one call and claimed the file was written; the file did not exist. With "you must use the terminal tool; run exactly this command", it worked.
- **Tool-argument JSON is sometimes malformed** (`tool_call 'calls' is not valid JSON`). Hermes returns the error to the model, which usually retries. The `remember` call needed an exact-argument prompt. A multi-step `read` after `search` did not complete reliably. Recall worked when the search result itself held the fact.
- **Memory extraction needs substance.** A one-line `remember` extracted 0 memories (the extraction model is the VLM alias). A two-message submission extracted 1.

## Open items (spec 04)

- **Browser MCP tools** (spec 04 and spec 09 `deploy/browser/`): not deployed. Only `hermes` gets browser tools.
- **LiteLLM MCP gateway**: Hermes connects to OpenViking's MCP endpoint directly, not through the gateway. Register it with LiteLLM when the gateway's MCP support is set up.
- **Egress and network policy** (spec 04 and spec 08 part B, step 11): the Kubernetes API server is reachable from the pod's network (TLS verification fails, but a route exists). Istio `REGISTRY_ONLY` and the NetworkPolicy must close that.
- **`readOnlyRootFilesystem`**: not set. The Hermes install writes its runtime files under the image path. Needs a test.
- **Flux**: the `hermes` Kustomization is not in `clusters/dsm-shai/` yet. It goes in after the branch is merged to `main`.

## Operation

```sh
kubectl -n hermes logs deploy/hermes -c hermes --tail=100                       # gateway log
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes doctor'                    # config check
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes -z "..."'                  # one-shot prompt
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes logs | grep tool'          # tool activity
```
