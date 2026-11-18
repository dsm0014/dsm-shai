# Spec 12 — Claude Haiku via Claude Code CLI (subscription)

**Status:** IN PROGRESS

## Purpose

Give Hermes access to Claude Haiku using the owner's Claude subscription, with no Anthropic API key and no API credits. Haiku is called through the Claude Code CLI (`claude -p`) authenticated by a long-lived subscription token (`claude setup-token`). This replaces the earlier plan of an API key behind a LiteLLM `haiku` alias: a subscription token cannot be used from a third-party gateway such as LiteLLM and the API bills separately. The file name is kept so links stay valid. Depends on specs 07 (secrets), 08 (mesh), 09 (LiteLLM) and 11 (egress proxy). Spec 13 uses the `haiku` tier defined here.

## Behavior

**Amendment to the local-only rule (owner decision recorded by this spec)**
- The only permitted cloud model is Claude Haiku, reached only through the CLI wrapper, on the subscription. LiteLLM stays local-only: no Anthropic provider, alias or key is added to it, and spec 09 is unchanged. `CLAUDE.md` is amended in the same PR.
- No automatic fallback in either direction. Callers choose the tier by configuration.

**Wrapper**
- `deploy/hermes/jobs/claude-haiku/claude-haiku.sh` (mounted read-only at `/opt/jobs/claude-haiku/`): prompt on stdin, answer on stdout, `claude -p --model haiku --tools ""` so the CLI has no tools. The model name is pinned in one variable (`CLAUDE_HAIKU_MODEL`).
- It unsets `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` before every call, so a stray API key can never be used, and `--preflight` fails if one is set. Auth is `CLAUDE_CODE_OAUTH_TOKEN` only.
- Limits: `CLAUDE_HAIKU_PARALLEL` concurrent calls (default 2, by `flock` slots), `CLAUDE_HAIKU_DAILY_CALLS` per day (default 200), `CLAUDE_HAIKU_TIMEOUT` seconds (default 120), a `disabled` flag file in `/opt/data/claude-haiku/`. Subscription use is bounded by plan rate limits, not dollars, so the caps are call counts.
- Audit: append-only `/opt/data/claude-haiku/audit.jsonl` with time, status, model, input size and duration. Never prompt or response text, never the token.

**Credential**
- The token is stored as `deploy/secrets/hermes-claude.sops.yaml` (ciphertext only), created by `scripts/set-claude-token.sh`, which reads it silently and refuses `sk-ant-api` keys. Delivered to the hermes pod only, as `CLAUDE_CODE_OAUTH_TOKEN` through an optional `secretKeyRef`, so the pod starts without it and the wrapper fails closed.
- Rotation: `claude setup-token`, re-run `set-claude-token.sh`, commit, let Flux reconcile, restart Hermes, run `make claude-haiku-preflight`, revoke the old token.
- `scripts/check-sops.sh` also scans for `sk-ant-` strings.

**Installation**
- The CLI is installed on the host and copied to `/opt/data/tools/claude` on the Hermes PVC (`kubectl cp`), so no package registry is added to the egress allowlist. `DISABLE_AUTOUPDATER=1` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` are set.

**Egress**
- `api.anthropic.com` is added to the Squid CONNECT allowlist (`deploy/istio/egress/squid.conf`). The proxy already accepts only the hermes service account, so the Hermes pod is the only workload that can reach Anthropic. Other namespaces cannot. This widens the hermes pod's internet reach by one host; the README says so.

**Privacy**
- Anything sent to Haiku is processed by Anthropic under the consumer terms of the subscription. The README lists what must not be sent (memory dumps, secrets, personal data). A request goes to Haiku only when a caller invokes the wrapper.

## Acceptance Criteria

- [ ] `deploy/secrets/hermes-claude.sops.yaml` is ciphertext only; `scripts/check-sops.sh` (with the `sk-ant-` pattern) passes; the token appears only in the `hermes` namespace Secret.
- [ ] `make claude-haiku-preflight` passes in the pod, and fails when `ANTHROPIC_API_KEY` is set.
- [ ] `echo "reply OK" | claude-haiku.sh` in the pod returns text, writes one audit line, and the Anthropic console shows no API usage.
- [ ] The wrapper refuses to run with the `disabled` flag, without a token, and after the daily cap; two parallel calls run and a third waits (offline test with a fake CLI).
- [ ] From the hermes pod `https://api.anthropic.com` works through the proxy; from another namespace it is refused; the proxy log shows the allowed call.
- [ ] `chat`, `embed` and `vision` through LiteLLM still work and LiteLLM has no Anthropic configuration.
- [ ] Logs and audit files contain no prompt, response or token.
- [ ] `CLAUDE.md` and `deploy/hermes/README.md` carry the amendment, the data-handling statement, the install steps and the rotation procedure.
