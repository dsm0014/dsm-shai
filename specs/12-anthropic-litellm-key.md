# Spec 12 — Claude Haiku via Claude Code CLI (subscription)

**Status:** IN PROGRESS

## Purpose

Give Hermes access to Claude Haiku using the owner's Claude subscription, with no Anthropic API key and no API credits. Haiku is called through the Claude Code CLI (`claude -p`) authenticated by a long-lived subscription token (`claude setup-token`). This replaces the earlier plan of an API key behind a LiteLLM `haiku` alias: a subscription token cannot be used from a third-party gateway such as LiteLLM and the API bills separately. The file name is kept so links stay valid. Depends on specs 07 (secrets), 08 (mesh), 09 (LiteLLM) and 11 (egress proxy). Spec 13 uses the `haiku` tier defined here.

## Behavior

**Amendment to the local-only rule (owner decision recorded by this spec)**
- The only permitted cloud model is Claude Haiku, reached only through the CLI wrapper, on the subscription. LiteLLM stays local-only: no Anthropic provider, alias or key is added to it, and spec 09 is unchanged. `CLAUDE.md` is amended in the same PR.
- No automatic fallback in either direction. Callers choose the tier by configuration.

**Wrapper**
- `deploy/hermes/jobs/claude-haiku/claude-haiku.sh` (mounted read-only at `/opt/jobs/claude-haiku/`): prompt on stdin, answer on stdout, `claude -p --model haiku --tools ""` so by default the CLI has no tools. With `CLAUDE_HAIKU_WEB=1` (research mode, spec 15) it gets exactly two tools, `WebSearch` and `WebFetch`: `--tools "WebSearch,WebFetch"`, `--permission-mode dontAsk`, Bash, Edit, Write, NotebookEdit, Agent and `mcp__*` disallowed, `--max-turns` (`CLAUDE_HAIKU_WEB_TURNS`, default 12), an empty scratch working directory, and `HTTPS_PROXY` pointed at the open-web proxy listener (`CLAUDE_HAIKU_WEB_PROXY`, default `http://squid.egress-proxy.svc:3129`). The model name is pinned in one variable (`CLAUDE_HAIKU_MODEL`).
- It unsets `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` before every call, so a stray API key can never be used, and `--preflight` fails if one is set. Auth is `CLAUDE_CODE_OAUTH_TOKEN` only.
- Limits: `CLAUDE_HAIKU_PARALLEL` concurrent calls (default 2, by `flock` slots), `CLAUDE_HAIKU_DAILY_CALLS` per day (default 200), `CLAUDE_HAIKU_TIMEOUT` seconds (default 120), a `disabled` flag file in `/opt/data/claude-haiku/`. Subscription use is bounded by plan rate limits, not dollars, so the caps are call counts.
- Audit: append-only `/opt/data/claude-haiku/audit.jsonl` with time, status, model, input size and duration. Never prompt or response text, never the token.

**Credential**
- The token is stored as `deploy/secrets/hermes-claude.sops.yaml` (ciphertext only), created by `scripts/set-claude-token.sh`, which reads it silently and refuses `sk-ant-api` keys. Delivered to the hermes pod only, as `CLAUDE_CODE_OAUTH_TOKEN` through an optional `secretKeyRef`, so the pod starts without it and the wrapper fails closed.
- Rotation: `claude setup-token`, re-run `set-claude-token.sh`, commit, let Flux reconcile, restart Hermes, run `make claude-haiku-preflight`, revoke the old token.
- `scripts/check-sops.sh` also scans for `sk-ant-` strings.

**Installation**
- The CLI is baked into a custom image, `deploy/hermes/image/Dockerfile`, built `FROM` the pinned upstream Hermes image (the general place for custom additions). `scripts/build-hermes-image.sh` builds it and loads it into k3s containerd (no registry); the main `hermes` container uses the local tag with `imagePullPolicy: IfNotPresent`. Nothing is downloaded or copied at runtime, and no package registry is added to the egress allowlist. `DISABLE_AUTOUPDATER=1` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` are set.

**Egress**
- `api.anthropic.com` is on the restricted Squid listener (`:3128`, `deploy/istio/egress/squid.conf`). The proxy accepts only the hermes service account, so the Hermes pod is the only workload that can reach Anthropic. Other namespaces cannot. In research mode the wrapper uses the open listener (`:3129`, any public host) so `WebFetch` can reach the pages it is asked to read; private and cluster addresses stay denied. The README says so.

**Privacy**
- Anything sent to Haiku is processed by Anthropic under the consumer terms of the subscription. The README lists what must not be sent (memory dumps, secrets, personal data). A request goes to Haiku only when a caller invokes the wrapper.

## Verification notes (2026-11-18)

- Through the proxy, the hermes pod reaches `api.anthropic.com` (squid log: `TCP_TUNNEL/200`) and is refused for other hosts (`TCP_DENIED/403` for `example.com`). A `litellm` pod is reset by the proxy (Istio policy allows only the hermes service account).
- **Gap found and closed (same day):** the `litellm` pod could reach `api.anthropic.com` directly (a real HTTPS request returned HTTP 404 from Anthropic) because the `litellm` namespace had no egress NetworkPolicy. `deploy/litellm/egress-networkpolicy.yaml` (LiteLLM: DNS, Ollama 11434, Postgres 5432, HBONE 15008; Postgres: DNS and HBONE) and `deploy/openviking/egress-networkpolicy.yaml` (DNS, LiteLLM 4000, HBONE) now block it. Before and after were measured on the same pod: without the policy `REACHED (http 404)`, with it `SSLEOFError`. Chat, embed, models and OpenViking health still return 200 afterwards.
- **Testing pitfall:** under ambient mode a plain TCP `connect()` always succeeds, because the in-pod redirect to ztunnel accepts the connection locally even when the onward hop is blocked. Egress tests must make a real HTTPS request and look for data. An earlier note here that every namespace was open was a false positive from a connect-only test.
- Still without a default-deny egress policy: `ollama` (needs internet for model pulls), `monitoring`, `istio-system`.

## Acceptance Criteria

- [x] `deploy/secrets/hermes-claude.sops.yaml` is ciphertext only; `scripts/check-sops.sh` (with the `sk-ant-` pattern) passes; the token appears only in the `hermes` namespace Secret. Verified 2026-11-19: `check-sops.sh` passes; the only Secret with a Claude token key in the cluster is `hermes/hermes-claude`.
- [x] The custom image builds and loads (`scripts/build-hermes-image.sh`), the pod runs from it as user 10000, and `claude --version` works in it. Verified 2026-11-18.
- [x] `make claude-haiku-preflight` passes in the pod, and fails when `ANTHROPIC_API_KEY` is set. Pass case verified in the pod; the fail-with-API-key case is verified offline by `make test`.
- [x] `echo "reply OK" | claude-haiku.sh` in the pod returns text, writes one audit line, and the Anthropic console shows no API usage. Verified: returned text in 1.9 s, one audit line (no content). The Anthropic console API-usage check is still open.
- [x] The wrapper refuses to run with the `disabled` flag, without a token, and after the daily cap; two parallel calls run and a third waits (offline test with a fake CLI). Verified offline: `make test` (9 tests, fake CLI) covers the disabled flag, missing token, daily cap, a 2-parallel cap with the third waiting, API key unset, timeout and no content in the audit.
- [x] From the hermes pod `https://api.anthropic.com` works through the proxy; from another namespace it is refused; the proxy log shows the allowed call. Verified 2026-11-18 with real HTTPS requests: hermes via the proxy works, other hosts get 403, a `litellm` pod is reset by the proxy, and direct requests from `litellm`, `openviking`, `open-webui` and hermes are blocked.
- [ ] `chat`, `embed` and `vision` through LiteLLM still work and LiteLLM has no Anthropic configuration. Partly verified 2026-11-19: `chat` (hermes key, 200) and `embed` (200 in the LiteLLM log from the real consumer); LiteLLM ConfigMap and Deployment contain no Anthropic or Claude string. Open: a `vision` request (needs the Open WebUI consumer key; no request seen in 24 h).
- [x] Logs and audit files contain no prompt, response or token. Verified 2026-11-19: LiteLLM logs (24 h) have no `anthropic`, `sk-ant` or key strings; `claude-haiku/audit.jsonl` holds only time, status, model, bytes and duration.
- [x] `CLAUDE.md` and `deploy/hermes/README.md` carry the amendment, the data-handling statement, the install steps and the rotation procedure. Verified 2026-11-19.
