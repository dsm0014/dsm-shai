# LiteLLM MCP Gateway: Registering Servers and Per-Key Tool Access

**Tags:** litellm, mcp, tool-access, browser, openviking, spec-09

Source: docs.litellm.ai `/docs/mcp` and `/docs/mcp_control` (summarized fetch, so verify field names against the pinned LiteLLM version).

## Registering MCP servers

Three routes: `mcp_servers:` in `config.yaml`, the Admin UI ("MCP Servers"), or the management API (`POST/PUT /v1/mcp/server`).

```yaml
mcp_servers:
  playwright:
    url: http://browser-mcp.browser.svc:8931/mcp
    transport: http            # http | sse | stdio
    description: headless browser
    allowed_tools: [browser_navigate, browser_snapshot]   # server-level allowlist
    access_groups: [browsing]
  openviking:
    url: http://openviking.openviking.svc:1933/mcp        # only if OpenViking exposes MCP
    transport: http
    auth_type: bearer_token
    auth_value: os.environ/OPENVIKING_MCP_TOKEN
```
- `auth_type`: `api_key | bearer_token | basic | oauth2 | aws_sigv4`. `static_headers` and `extra_headers` forward custom headers. `server_id` pins permissions if the URL changes. `allow_all_keys: true` exposes a server to every key (do not set it here).
- `stdio` servers run as child processes of the proxy and are disabled unless `LITELLM_ENABLE_MCP_STDIO=true`. dsm-shai should use network (http) servers in their own pods, so the browser pod can be sandboxed.
- Servers defined in `config.yaml` persist in the DB only with `store_model_in_db: true` (or `supported_db_objects: ["mcp"]`). UI and API registrations live in the DB.
- OpenViking's own MCP endpoint and port are not confirmed. Check [[openviking-service]] before writing the entry.

## Calling the gateway

- One MCP endpoint: `POST /mcp/`, authenticated with the `x-litellm-api-key: Bearer <virtual-key>` header.
- Narrow by server with the `x-mcp-servers: a,b` header or URL namespacing (`/playwright/mcp`). Per-server upstream auth headers use `x-mcp-<alias>-<header>`.
- OpenAI Responses API clients can use a `tools` entry with `type: mcp` and `server_url: "litellm_proxy"`.

## Per-key access control (the allowlist requirement)

Set through `object_permission` on a key (or team or org) via `/key/generate` or the UI. `config.yaml` cannot grant per-key access.

```json
{
  "key_alias": "hermes",
  "object_permission": {
    "mcp_servers": ["playwright", "openviking"],
    "mcp_tool_permissions": {"playwright": ["browser_navigate", "browser_snapshot"]}
  }
}
```
- Server permissions combine as an intersection of key and team grants, plus any access groups. The org acts as a ceiling. Keys inherit team permissions unless they define their own.
- `"mcp_servers": ["no-mcp-servers"]` denies every server, which is the right setting for the `open-webui` and `openviking` consumer keys.
- `mcp_tool_permissions` limits tools per server, and key and team values intersect.
- This all needs the Postgres DB, which spec 09 already includes. The provisioning script should make these `/key/generate` calls idempotently and the README should record them, because the grants live only in the DB (so they also belong in the spec 07 backup scope).

## Metrics

`litellm_mcp_tool_calls_total` and `litellm_mcp_tool_call_spend_metric` (labelled by tool, server, key, team) are exported through the Prometheus callback.

## Assumption flagged in spec 09

"Browser routing" is implemented as an MCP browser tool behind this gateway, not a separate proxy product. The LiteLLM docs support this reading, since MCP servers are the only browser-adjacent mechanism the gateway documents.
