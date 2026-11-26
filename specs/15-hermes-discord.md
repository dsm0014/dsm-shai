# Spec 15 — Hermes on Discord, Swarm Commands and Haiku Web Research

**Status:** IN PROGRESS (egress and the Haiku research mode are built and tested offline; the Discord side is not built)

## Purpose

Give the owner a chat interface to Hermes and the swarm (spec 13) from Discord, and give Haiku (spec 12) access to the public web for research. Hermes already runs the long-lived gateway (`hermes gateway run`), whose Discord adapter needs only a bot token, an allowlist and outbound access. The swarm is driven by deterministic slash commands, not by asking the 9B model to run shell commands. Depends on specs 04 (Hermes), 07 (secrets), 08 (egress proxy), 11 (proxy, token handling), 12 (Haiku wrapper) and 13 (swarm).

## Behavior

**Egress (built)**
- One Squid proxy, two listeners (`deploy/istio/egress/squid.conf`):
  - `:3128` restricted, the pod-wide default (`HTTPS_PROXY`): CONNECT on 443 to the five GitHub hosts, `api.anthropic.com`, `discord.com`, `.discord.gg` (the gateway host and the `resume_gateway_url` host Discord returns in READY), `cdn.discordapp.com` and `media.discordapp.net`.
  - `:3129` research: CONNECT on 443 to any public host. Used only by `claude-haiku.sh` when `CLAUDE_HAIKU_WEB=1`.
  - Both listeners deny private, loopback, link-local and CGNAT destinations by address, whatever the hostname.
- The local model and its tools (terminal, `curl`, `git`) use `:3128` through `HTTPS_PROXY`. They never receive the open listener by configuration. The split is defence in depth, not isolation: any process in the pod could call `:3129` explicitly. The hermes service account is the only caller the mesh admits (`squid-from-hermes`, ports 3128 and 3129).
- Voice is out of scope (Discord voice uses UDP, which an HTTP proxy cannot carry). `/voice` stays unused.

**Haiku web research (built)**
- `CLAUDE_HAIKU_WEB=1 claude-haiku.sh` runs `claude -p --model haiku` with only `WebSearch` and `WebFetch`, `--permission-mode dontAsk`, Bash, Edit, Write, NotebookEdit, Agent and `mcp__*` disallowed, `--max-turns` 12, an empty scratch directory, and `HTTPS_PROXY` set to the research listener. Without the variable the wrapper is unchanged (no tools).
- `WebSearch` is executed by Anthropic's backend. `WebFetch` runs in the pod and reaches the target host through the research listener, and it sends only the hostname to `api.anthropic.com` for its domain check. Fetched pages are untrusted input: the model has no tool that can act on them, and callers wrap the result in the `UNTRUSTED_CONTENT` markers (spec 13) before using it. Research mode counts against the same daily call cap, parallelism cap and kill switches as every other wrapper call. Callers opt in per call; the swarm does not set it today.

**Discord interface (not built)**
- The gateway runs with `DISCORD_BOT_TOKEN` and the allowlist from a SOPS secret `hermes-discord` (optional, so the pod starts without it). Token, user IDs and channel IDs are ciphertext only; the repository is public. `DISCORD_PROXY=http://squid.egress-proxy.svc:3128`.
- Authorization fails closed. A Discord user who can chat with Hermes has its terminal tool, and so the pod's `GITHUB_TOKEN` and Claude subscription token. The bot answers only the owner (`DISCORD_ALLOWED_USERS`) in one private channel (`DISCORD_ALLOWED_CHANNELS`), `allow_admin_from` lists the owner only, `DISCORD_ALLOW_ALL_USERS` is never set, and the `discord_admin` toolset (server administration) is disabled for the Discord platform. Message Content Intent is on; Server Members Intent stays off.
- Swarm commands are `quick_commands` of `type: exec`, each calling one script, `deploy/hermes/jobs/swarm/swarm-chat.sh <verb> [task]`:

  | Command | Does |
  |---|---|
  | `/swarm-status` | what `make swarm-status` prints |
  | `/swarm-plan <task>` | dry run, spends nothing |
  | `/swarm-run <task>` | background run, as `make swarm-run` |
  | `/swarm-stop` | SIGTERM to the swarm (the lock is released on exit) |

  The script validates the task name against `/opt/jobs/swarm-*/task.yaml`, never builds a shell string from chat text, and refuses anything else with a usage line. The existing swarm guards are unchanged: `SWARM_ALLOWED_REPOS`, caps, the one-run lock, the `disabled` flags and `hermes pause`.
- Results come back through a no-agent cron job (`--no-agent --script ... --deliver discord`, registered paused) that prints the new lines of `/opt/data/swarm/digest.log` since its last run and nothing when there are none (a silent tick). The bot token never enters the swarm's environment, and the swarm engine is not changed. Spec 14's pull request URLs appear the same way. Nothing in Discord can merge.
- Free chat (`@bot` in a thread) goes to the local model for questions only. Starting work is by the commands above, because the 9B model is unreliable at choosing tools (`deploy/hermes/README.md`).
- Anything typed in Discord is sent to Discord's servers. The README says not to paste secrets or personal data.

## Research findings (2026-11-18, from the upstream docs and source on `main`)

Facts the design relies on, and what is still unverified.
- Adapter: `plugins/platforms/discord/adapter.py`, not `gateway/platforms/discord.py`. `DISCORD_PROXY` is read by Hermes and passed to discord.py as `proxy=`, which covers REST, the gateway WebSocket and CDN downloads. If it is unset, `HTTPS_PROXY` is used (`gateway.trust_env` defaults true). Hosts: `discord.com/api`, `wss://gateway.discord.gg/` and the `resume_gateway_url` host from READY, `cdn.discordapp.com`. Upload goes through REST.
- A blocked host shows as a fast connect error or a 30 s startup timeout, not a hang. `models.dev` is fetched lazily with a 15 s deadline and may stall one catalog lookup under default-deny.
- Cron delivery accepts `discord` (the home channel, `DISCORD_HOME_CHANNEL`) and `discord:<numeric channel id>` (core code). `discord:#name` depends on a channel directory that was not read. `--script` must resolve inside `HERMES_HOME/scripts` (symlinks out are rejected), so the init container copies it there. Scripts cannot read `DISCORD_BOT_TOKEN`. Proxy variables probably pass through to scripts.
- `quick_commands` `type: exec`: the dispatch order suggests the LLM is bypassed. Not found in source: argument passing, how output is returned, timeout, working directory, environment. Exec commands appear to skip the per-command access check (`user_allowed_commands`), so the user allowlist is the control. They are probably not registered as Discord application commands (typed `/name` only).
- Claude Code: `--allowedTools` only pre-approves; `--tools` restricts the built-in set. `WebFetch` runs locally and needs egress to the target host. The docs do not say whether `WebSearch` works with a subscription OAuth token, whether `WebFetch` honours `HTTPS_PROXY`, or whether `--tools` limits subagents (`Agent` is disallowed regardless).

## Acceptance Criteria

- [x] `squid.conf` has the restricted and research listeners, the Discord hosts and the private-address deny; the proxy Service, the Istio policy and the hermes NetworkPolicy carry port 3129. Written 2026-11-18; **not yet verified in the cluster**.
- [x] `claude-haiku.sh` in research mode passes only `WebSearch` and `WebFetch`, disallows the other tools, uses the research proxy and an empty working directory; default mode is unchanged. Verified offline 2026-11-18 (`make test`, wrapper tests).
- [x] `squid -k parse` accepts `squid.conf` and the process starts under the pod's restrictions (uid 13, read-only root). Verified 2026-11-26 in the running pod, which has those restrictions; Docker was not used.
- [x] In the cluster, from the hermes pod: `:3128` reaches `api.github.com` and `discord.com` and refuses `example.com`; `:3129` reaches `example.com` and refuses an address in 10.0.0.0/8 and a hostname that resolves to one; another namespace is refused on both ports; `curl` without a proxy fails. Verified 2026-11-26 (`deploy/istio/egress/README.md`).
- [ ] `echo "..." | CLAUDE_HAIKU_WEB=1 claude-haiku.sh` in the pod returns an answer that cites a page fetched in this run, the Squid log shows the tunnel on `:3129`, and the audit line records one call and no content. `WebSearch` working on the subscription token is checked here. If it does not, the spec records that and uses `WebFetch` only.
- [ ] In research mode the CLI's `system/init` event lists exactly `WebSearch` and `WebFetch`, and a prompt that asks it to run a shell command or read `/opt/data` fails.
- [ ] `hermes-discord` SOPS secret holds the token, user IDs and channel IDs as ciphertext; `bash scripts/check-sops.sh` and `git grep -E 'sk-ant-|ghp_|github_pat_' -- . ':!*.md'` are clean; no ID or token appears in a ConfigMap, log or audit file.
- [ ] The gateway connects to Discord through `DISCORD_PROXY` (startup log shows ready, with no 30 s timeout), answers the owner in the allowed channel, ignores another user and another channel, and `discord_admin` is not in the Discord toolset (`hermes tools --summary`).
- [ ] On a test `quick_commands` entry, the criteria the docs left open are recorded: the LLM is bypassed, arguments are passed (and how), stdout and the exit code come back, the timeout, the working directory, and whether a non-admin is blocked. The swarm commands are built only on what this shows.
- [ ] `swarm-chat.sh` is tested offline: each verb maps to the matching `swarm.py` call, an unknown verb or task, a path, a shell metacharacter and an empty argument exit 2 with usage, and the script never passes chat text to a shell. `make swarm-test` includes it.
- [ ] Live: `/swarm-plan swarm-example` returns the plan, `/swarm-run swarm-example` starts a run, `/swarm-status` shows it running, `/swarm-stop` stops it and releases the lock; a second `/swarm-run` reports `skipped: locked`; `hermes pause` stops it.
- [ ] The digest cron job registers paused, `hermes cron resume <id>` posts a new digest line to the Discord channel within two minutes of the swarm writing it, posts nothing when there is no new line, and posts an alert when forced to fail. `--deliver discord:<channel id>` versus the home channel is settled and recorded.
- [ ] `deploy/hermes/README.md` documents the Discord setup (developer portal steps, intents, invite URL, secret creation), the commands, the allowlist rationale, research mode and how to turn each off (unset `DISCORD_BOT_TOKEN`, `touch /opt/data/claude-haiku/disabled`, remove the `3129` rule). `deploy/istio/egress/README.md` documents both listeners.
