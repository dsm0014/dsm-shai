# deploy/hermes

Hermes Agent (spec 04), namespace `hermes`. Status: **deployed, gateway running, blocked on the model context floor** (see below).

## Image

`docker.io/nousresearch/hermes-agent:v0.23.1@sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08`

Deviation from spec 04: the spec asks for a build from `deploy/hermes/`. This cluster has no container build daemon (no Docker daemon, no root for `k3s ctr`). The upstream project publishes this image on every release, so it is pinned by digest instead of built here. Bump it by tag and digest together.

## Config

`config.yaml` (ConfigMap `hermes-config`) is copied to `/opt/data/config.yaml` by an init container on each start:

- `model.provider: custom`, `base_url: http://litellm.litellm.svc:4000/v1`, `model.default: chat`.
- The key comes from env `OPENAI_API_KEY`, which is the LiteLLM virtual key `hermes` (allowlist `chat`, budget 20, 60 rpm), from SOPS Secret `hermes-secrets`.
- No direct Ollama URL. No cloud provider.

Hermes data (`HERMES_HOME`) is `/opt/data` on PVC `hermes-home` (10Gi, `local-path`). The image uses that path, not `~/.hermes`. The init container sets it to owner `10000` (`hermes`) with mode `0750`. Hermes refuses to start with a world-writable `/opt/data`.

Headless: `args: ["gateway", "run"]`, the foreground gateway that the image recommends for containers. `hermes -z "..."` and interactive `hermes chat` both use the running gateway.

## Current blocker: 64K context floor

Hermes refuses any model below 64,000 tokens of context (`agent/agent_init.py`, `_enforce_minimum_context`). Observed error:

> Model chat has a context window of 32,768 tokens, which is below the minimum 64,000 required by Hermes Agent.

For a local endpoint, the floor is satisfied only when Ollama really serves 64K, through `OLLAMA_CONTEXT_LENGTH` or `model.ollama_num_ctx`. Measured on this card (RTX 4080, 16 GiB, `qwen3:14b`, embed resident):

| Setting | Result |
|---|---|
| `OLLAMA_CONTEXT_LENGTH=32768`, KV `q8_0` (spec 02 baseline) | loads and serves 32k; 28.8k-token prompt verified; **below floor** |
| `OLLAMA_CONTEXT_LENGTH=65536`, KV `q8_0` | scheduler shrinks the loaded context to 40960 (predicted 14.9 GiB > 14.4 GiB available); **below floor** |
| `OLLAMA_CONTEXT_LENGTH=65536`, KV `q4_0` | still shrinks to 40960 (same estimate); **below floor** |

Setting `model.context_length` to 64000 in config would pass Hermes's check but not the server's real window. Ollama truncates any prompt longer than its loaded context to about half, silently. That is not an acceptable workaround.

Decision needed (see the status message for options): change the chat model to one with a native 64K window that fits the card, relax the Hermes floor in a rebuilt image, or accept a smaller window with Hermes configured for it.

## Safety posture (as deployed)

- ServiceAccount `hermes` with `automountServiceAccountToken: false`. No RBAC.
- `/workspace` is an `emptyDir` with `sizeLimit: 10Gi`.
- No `hostPath`, no Docker or containerd socket.
- Resource requests 500m/2Gi, limits 2/4Gi.

Not yet met (spec 04):

- **Non-root container.** The upstream image's PID 1 is s6-overlay running as root. It remaps the UID and then drops to `hermes` (UID 10000) for the workload. Hermes runs as non-root, but the container's init does not, so `runAsNonRoot` cannot be set. Needs an image decision (see the same status message).
- `readOnlyRootFilesystem`, `seccompProfile`, dropped capabilities: deferred until the init model is settled.
- Egress allowlist (Istio `REGISTRY_ONLY`) and the NetworkPolicy: step 11.
- OpenViking MCP wiring (`http://openviking.openviking.svc:1933/mcp`, key from the `openviking` account): needs a tenant key for Hermes. Route through the LiteLLM MCP gateway if the OSS release supports it, else direct; not yet registered.

## Operation

```sh
kubectl -n hermes logs deploy/hermes -c hermes --tail=100       # gateway log
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes doctor'    # config check
kubectl -n hermes exec deploy/hermes -- sh -c 'hermes -z "..."'  # one-shot prompt (needs the gateway running)
```
