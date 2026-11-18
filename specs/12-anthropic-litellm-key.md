# Spec 12 — Anthropic Key in LiteLLM

**Status:** TODO

## Purpose

Add the owner's Anthropic API key to the LiteLLM gateway (spec 09) so that selected consumers can call Claude Haiku through the same OpenAI-compatible endpoint, alongside the local Ollama aliases. This is a deliberate, narrow exception to the "everything runs locally; no cloud model providers" constraint in `CLAUDE.md`. Depends on specs 07 (secrets), 08 (mesh and egress), 09 (LiteLLM) and 11 (egress proxy).

## Behavior

**Amendment to the local-only rule (owner decision recorded by this spec)**
- Anthropic is the only permitted cloud provider, and only for the alias `haiku`. No other cloud provider, model or alias is added. `CLAUDE.md`, spec 09 ("No cloud fallbacks") and the spec 09 criterion "No cloud provider is configured" are amended in the same PR to say so.
- No automatic fallback in either direction: an Ollama outage never reroutes to Anthropic, and an Anthropic failure never reroutes to Ollama. `router_settings.fallbacks` stays empty and `num_retries` stays 0.

**Model alias**
- New alias `haiku` in `deploy/litellm/config.yaml`: `anthropic/claude-haiku-5-5`, `api_key: os.environ/ANTHROPIC_API_KEY`, timeout 120 s, `max_parallel_requests` set from a documented value (default 8; cloud calls do not compete for the GPU).
- The model id is pinned in one place so a model upgrade is a one-line change plus a re-run of the acceptance checks.

**Credential**
- The key is stored as `deploy/secrets/litellm-anthropic.sops.yaml` (ciphertext only, added to `deploy/secrets/kustomization.yaml`) and delivered to the LiteLLM pod only, as env var `ANTHROPIC_API_KEY` through `secretKeyRef`. It is never in a ConfigMap, manifest, log, prompt, OpenViking or any other pod. Consumers never see it; they hold only LiteLLM virtual keys.
- The key is an Anthropic workspace key with a monthly spend limit set in the Anthropic console, as the hard cap behind LiteLLM's own budgets. Rotation: create the new key, `sops edit`, commit, let Flux reconcile, restart LiteLLM, run the acceptance check, revoke the old key. The procedure goes in `deploy/litellm/README.md`.
- The key is committed only after the spec 07 pre-commit secret scan (extended with the `sk-ant-` pattern) passes.

**Access control**
- Virtual keys get the `haiku` alias only by explicit allowlist. `hermes` gets it (for spec 13); `openviking` and `open-webui` do not. The `hermes` key's budget is split: a separate `max_budget` for `haiku` (default 5 USD per 30 days) so cloud spend cannot be hidden inside the existing local budget; exceeding it returns 429 and Hermes falls back to local-only work by its own configuration, not by LiteLLM.
- Requests with a missing, wrong or non-allowlisted key are rejected (401/403), as for the existing aliases.

**Egress**
- LiteLLM is the only workload that may reach `api.anthropic.com`. Egress goes through the spec 11 Squid proxy (`egress-proxy`, `:3128`) with `api.anthropic.com` added to its CONNECT allowlist; the allowlist change lives in `deploy/istio/egress/` and is reviewed there. LiteLLM sets `HTTPS_PROXY` with `NO_PROXY` for `.svc`, `.cluster.local` and the Ollama service.
- The proxy accepts `:3128` from the `litellm` and `hermes` service accounts only. The hermes pod does not gain a route to Anthropic: it reaches it only through LiteLLM. The GitHub-only hosts for hermes stay as spec 11 defines them.
- Other namespaces cannot reach the proxy or LiteLLM's cloud path.

**Privacy and observability**
- Prompt and response logging stays OFF (`turn_off_message_logging: true`). Because content now leaves the machine, the README states plainly that anything sent to `haiku` is processed by Anthropic under its API terms, and lists what Hermes must not send (memory dumps, secrets, personal data). A request is routed to `haiku` only when the caller names that alias.
- Prometheus metrics (spec 06) show requests, tokens and spend per key and per model, so `haiku` usage is visible. An alert fires when `haiku` spend in a day exceeds a documented threshold.

## Acceptance Criteria

- [ ] `deploy/secrets/litellm-anthropic.sops.yaml` is ciphertext only; `git grep -E 'sk-ant-'` is clean outside it; the pre-commit scan, with the `sk-ant-` pattern, passes; `kubectl get cm,secret -A -o yaml` shows the key only in the `litellm` namespace Secret.
- [ ] A `haiku` chat request through `litellm.litellm.svc:4000/v1` with the `hermes` key succeeds and streams; the same request with the `open-webui` or `openviking` key returns 403; a missing or wrong key returns 401.
- [ ] `chat`, `embed` and `vision` still work unchanged (spec 09 checks pass).
- [ ] With the Anthropic host blocked at the proxy, a `haiku` request fails with an error and does not fall back to `chat`; with Ollama stopped, a `chat` request does not reach Anthropic (proxy log shows no call).
- [ ] From the hermes pod, `https://api.anthropic.com` is refused (direct and through the proxy path not mapped to it); from the `litellm` pod it succeeds through the proxy; from another namespace it is reset; the proxy log shows each.
- [ ] Exceeding the `hermes` `haiku` budget returns 429 for `haiku` while `chat` keeps working.
- [ ] `haiku` request counts, tokens and spend appear in Prometheus per key; the spend alert rule loads; logs contain no prompt or response content and no key.
- [ ] A LiteLLM Postgres backup and restore (spec 07) preserves the virtual keys and the `haiku` allowlist; a key rotation following the README leaves the gateway serving `haiku`.
- [ ] `CLAUDE.md`, spec 09 and `deploy/litellm/README.md` carry the amendment, the data-handling statement and the rotation procedure.
