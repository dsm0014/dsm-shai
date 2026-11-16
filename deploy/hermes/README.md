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

## Tool-use investigation (2026-11-16)

Controlled tests with `llama3.1:8b` (and `mistral-nemo:12b` as a candidate, removed afterwards):

- A single tool call, a multi-step answer after a tool result, 40 distractor tools, and a 10k-token system prompt: all 5/5 for llama. Streamed tool calls through LiteLLM: 5/5. So the model, gateway and streaming work in isolation.
- Hermes sends about 10.7k input tokens per call, and its tools go through Tool Search by default. In Hermes, the bridge calls (`tool_call` wrappers) failed with malformed JSON.
- With Tool Search off and the OpenViking tools limited to `find`, `remember`, `read` and `list` (`mcp_servers.openviking.tools.include`):
  - `read` by URI recalled the stored code 3/3, with no tool errors.
  - `search` failed because the model added a `detail` argument that OpenViking rejects (`detail` requires `mode='context'`).
  - `find` runs, but returns directory abstracts, so it does not surface `profile.md`.
  - An explicit shell task (`ls -S ... > file`) ran through the terminal tool and reported success, but produced no file in 1 of 2 runs. The model did not run the command it was given.

Conclusion (superseded by the next section): the earlier read was that the model could not follow multi-step instructions. The follow-up investigation found specific causes, so read "Why Hermes failed" before relying on this one. Hermes is still **not** reliably autonomous on `llama3.1:8b`.

## Why Hermes failed (investigation, 2026-11-16)

Method: capture the real request Hermes sends (`scripts/hermes-capture-proxy.py`), then replay it against any model with `scripts/bench-hermes-tools.py` (8 cases x 5 runs: three plain questions that need no tool, four single tool calls, one two-step task). The request is about 14k tokens: the 7.8k-character system prompt plus 29 tool schemas (about 53k characters). Hermes sends no `temperature`.

| Variant | Plain questions (15) | Tool calls (20) | Two-step (5) | Total (40) |
|---|---|---|---|---|
| `llama3.1:8b`, as Hermes runs it | 0 (called a tool every time) | 19 | 2 | 21 |
| same, `temperature 0.2` | 0 | 20 | 0 | 20 |
| same, only 10 tools | 0 | 19 | 0 | 19 |
| `llama3.1:8b` weights, corrected template | 15 | 0 (answered in prose and invented the results) | 5 | 20 |
| `qwen3:14b`, `reasoning_effort: none` | 15 | 20 | 5 | **40** |

Findings:

1. **The `llama3.1` Ollama template forces a tool call.** With tools present it rewrites the last user message to "respond with a JSON for a function call ... Question: ..." (`ollama show llama3.1:8b --template`). A plain question therefore gets a call to a tool that does not exist (`write`, `text`) or a wrong one (`text_to_speech` for "reply PONG"), and Ollama returns the invented call as message text. Temperature and tool count do not change this.
2. **Removing the forcing does not fix the model.** With the system-turn template, the same weights stop calling tools and make up the output (a file listing, file contents). The model cannot judge when a tool is needed. This is a model-quality limit, not only a template one.
3. **The model matters a lot.** `qwen3:14b` passed 40 of 40 on the same replay. It cannot be used because its native context is 40960 and Hermes requires 64,000 (see `deploy/ollama/README.md`). The next step is a model with a native context of at least 64K; candidates and results are recorded below.
4. **The coding persona was a test artifact.** On a CLI surface in a directory that looks like a code project, Hermes injects "You are a coding agent ... make changes through the tools, not the chat". `kubectl exec ... hermes -z` starts in `/opt/hermes`, which has a `pyproject.toml`, so the earlier README tests ran with that persona. `agent.coding_context: "off"` (now set in `config.yaml`) removes it, verified by capturing the request. The persona explained one failure ("reply PONG" calling the terminal); it did not explain the rest.
5. **Hermes tunes its prompt by model name, and ours is `chat`.** `TOOL_USE_ENFORCEMENT_MODELS` and the execution-guidance list (`agent/prompt_builder.py`) match substrings such as `qwen`, `gpt`, `gemma`, `mistral`. The LiteLLM alias `chat` matches none, so no model-specific guidance is applied. Not yet tested whether naming the alias after the model changes behaviour.
6. **Not the cause:** sampling (tested), tool count (tested), the LiteLLM and mesh path (a direct Ollama replay shows the same results), Tool Search (already off).

### Candidates (native context of at least 64K, fits 16 GiB)

`qwen3.5:9b` (256K, vision, tools), `gemma4:12b` (256K), `ministral-3:8b` (256K), `gpt-oss:20b` (128K, about 14 GB, little VRAM left at 64K). `gemma4:12b` and `ministral-3:8b` are downloaded but not yet benchmarked.

**`qwen3.5:9b`** (Ollama 0.40.16, same 8-case replay, 5 runs each):

| `reasoning_effort` sent | Plain (15) | Tool calls (20) | Two-step (5) | Total (40) |
|---|---|---|---|---|
| `none` (what `config.yaml` sends today) | 15 | 15 (5 failures) | 5 | 37 |
| not sent (thinking on, the model default) | 15 | 20 | 5 | **40** |
| `medium` | 15 | 19 | 5 | 39 |

- **Thinking must stay on.** With `reasoning_effort: none`, Ollama returned HTTP 500 (`XML syntax error ... element <function> closed by </parameter>`) on 4 to 6 of every 10 `read_file` calls: the model writes tool calls as XML, and Ollama's `qwen3.5` parser rejects a malformed one instead of returning it. Qwen's recommended sampling (`temperature 0.7, top_p 0.8, presence_penalty 1.5`) cut that to 2 of 10 but did not remove it. With thinking on, `read_file` succeeded 10 of 10. If this model is adopted, change `agent.reasoning_effort` away from `"none"`.
- **It fits.** Loaded at `num_ctx 65536` it uses 6.43 GiB (hybrid attention keeps the cache small), 0.31 GiB more for the embedding model; the device was at 9.7 of 16 GiB, about 6.6 GiB free. Native context is 262144, so the 64K floor is not a constraint.
- **Not yet tested:** real Hermes tasks through LiteLLM with this model (the replay sends Hermes's real request straight to Ollama, so it skips LiteLLM and Hermes's own loop), long multi-step tasks, and the memory-recall flow. Adopting it needs a change to `deploy/litellm/config.yaml` (`chat` alias), the model preload job, and the `reasoning_effort` above.

### After a restart

If Hermes replies with nothing or "waiting for the provider to recover", check mesh enrolment first (`deploy/istio/README.md`, "Restart recovery"). A `rollout restart` of `hermes` is reverted by Flux, so delete the pod.

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
