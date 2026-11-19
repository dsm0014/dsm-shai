# Egress proxy for the Hermes pod (specs 11, 12 and 15)

The hermes pod has no direct internet route (`deploy/hermes/egress-networkpolicy.yaml`). It reaches the internet through a Squid forward proxy in namespace `egress-proxy`. The container sets `HTTPS_PROXY` (and `NO_PROXY` for cluster hosts), so the nightly job, interactive Hermes and the Discord gateway all use it.

| Listener | Port | Allows (CONNECT on 443) | Used by |
|---|---|---|---|
| restricted | 3128 | `github.com`, `api.github.com`, `codeload.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`, `api.anthropic.com`, `discord.com`, `.discord.gg`, `cdn.discordapp.com`, `media.discordapp.net` | everything in the pod by default (`HTTPS_PROXY`) |
| research | 3129 | any public host | `claude-haiku.sh` with `CLAUDE_HAIKU_WEB=1` only (spec 15) |

Both listeners deny private, loopback, link-local and CGNAT destinations by address, whatever the hostname resolves to (`private_dst` in `squid.conf`); the proxy's own NetworkPolicy also excludes the RFC 1918 ranges. Everything else gets 403 and is logged. Edit `squid.conf`.

The split between the listeners is defence in depth: the local model and its shell tools hold `GITHUB_TOKEN` and follow `HTTPS_PROXY`, so they get only the restricted listener by configuration. A process in the pod can still call `:3129` explicitly, because the mesh admits the hermes service account on both ports. To turn research off, remove the `3129` rule from `deploy/hermes/egress-networkpolicy.yaml` (and `touch /opt/data/claude-haiku/disabled` stops every Haiku call).

- **Who may call it:** AuthorizationPolicy `squid-from-hermes` allows only `cluster.local/ns/hermes/sa/hermes` on 3128 and 3129 (deny-all baseline). The proxy's own egress is limited to DNS and port 443 on public addresses (`squid-egress`).
- **Why a proxy:** `outboundTrafficPolicy: REGISTRY_ONLY` is not enforced by ambient ztunnel (`deploy/istio/README.md`), a NetworkPolicy cannot match hostnames, and upstream Istio 1.30.8 has no documented way to make unregistered hosts fail. The options and the revisit triggers are in "Alternatives considered" below.
- **Flux:** stage `egress` (`clusters/dsm-shai/egress.yaml`, dependsOn `platform` and `istio`); the `hermes` stage dependsOn it.
- **Deviation from the spec:** the spec asked for SNI inspection (`ssl_bump peek` and `splice`). That needs an OpenSSL build of Squid and the pinned Ubuntu image is probably GnuTLS, so the allowlist is on the CONNECT target. Squid dials the allowed host itself, so a different SNI still only reaches GitHub. Use a `squid-openssl` image and add `ssl_bump` rules if SNI checking is wanted.

## Alternatives considered (decision 2026-11-17: keep Squid for now)

Spec 08 names ServiceEntry plus a waypoint or egress gateway as the intended mechanism. Squid is a deliberate deviation. The owner reviewed the options and chose to keep Squid, and to revisit later.

| Option | What it gives | Why not now |
|---|---|---|
| `outboundTrafficPolicy: REGISTRY_ONLY` | Mesh-wide deny of unregistered hosts (sidecar mode) | Not enforced by ambient ztunnel; measured here (Hermes reached `github.com`, `pypi.org`, `example.com`). |
| Ambient waypoint plus `ServiceEntry` (label `istio.io/use-waypoint`) | Mesh-native: SPIFFE identity, AuthorizationPolicy, Istio telemetry, allowlist as ServiceEntries in `deploy/istio/egress/` as spec 08 expects | Routes registered hosts only. Nothing in upstream Istio 1.30.8 makes unregistered hosts fail: the ztunnel chart at that version has no `egressPolicies` value (checked with `helm show values istio/ztunnel --version 1.30.8`), which appears in Solo.io's distribution docs. So the NetworkPolicy would still do the blocking. Also needs an AuthorizationPolicy (ambient ignores `exportTo`), TCP 15008 and DNS allowed for clients, and it is untested on this WSL2 ambient setup. Upstream docs for ambient egress control are thin (one blog post; the rest is vendor documentation). |
| Cilium FQDN policy | Hostname rules in the CNI | Would mean replacing flannel. Out of scope. |
| NetworkPolicy alone | Simple | Cannot match hostnames. |
| **Squid forward proxy (chosen)** | The proxy itself enforces the hostname allowlist, independent of the mesh dataplane. Tested locally in Docker (allow and deny). The pod can reach only the proxy at the network layer, so a client cannot bypass it. Common practice for agent egress. | Extra component to pin and patch; CONNECT-hostname match only (the image is GnuTLS, so no SNI inspection); Squid access log instead of Istio L7 telemetry; the allowlist lives in `squid.conf`, not in ServiceEntries. |

**Revisit when:** the cluster runs an Istio whose upstream ztunnel can deny unregistered destinations, or you want mesh identity and telemetry on egress, or a second workload needs hostname egress. A waypoint spike would keep `NIGHTLY_HTTPS_PROXY` as the seam: point it at the waypoint path, then retire Squid.

Sources (vendor-heavy; check upstream before relying on them): [Istio blog on egress routing](https://istio.io/latest/blog/2026/egress-dynamic-dns/), [Solo.io ambient egress migration](https://docs.solo.io/istio/1.31.x/traffic-management/egress/migrate-sidecar/), [agentgateway ambient egress](https://agentgateway.dev/docs/kubernetes/main/integrations/istio/ambient-egress/), [Alibaba Cloud ASM ambient egress](https://www.alibabacloud.com/help/en/asm/ambient/user-guide/manage-in-cluster-client-access-to-out-of-cluster-services).

## Verified locally (Docker, 2026-11-17) and what is still open

Run in Docker with the pod's restrictions (uid 13, read-only root with tmpfs on `/tmp`, `/var/spool/squid`, `/var/log/squid`, `/var/run`, all capabilities dropped): `squid -k parse` accepts `squid.conf` (one warning, `HTTP requires the use of Via`, from `via off`); the process starts; CONNECT to `api.github.com:443` tunnels (200); CONNECT to `example.com:443`, a plain `http://github.com` request and `github.com:8443` are all refused (403, logged `TCP_DENIED`). The image's Squid is built `--with-gnutls`, so `ssl_bump` is not available (confirmed). **Not yet verified in the cluster:** the pod starting under the mesh, the AuthorizationPolicy and the NetworkPolicy. Use the list below.

## Verified in the cluster (2026-11-17)

After the merge Flux created the namespace and the pod (Ready). From the hermes pod: `api.github.com` through the proxy returned 200; `example.com` and plain `http://github.com` were refused (proxy log `TCP_DENIED/403`); `curl` without the proxy failed (the NetworkPolicy blocks direct egress); a CONNECT from the `litellm` pod was reset by the mesh policy `squid-from-hermes`. Repeat these after any change to `squid.conf` or the policies:

1. `kubectl -n egress-proxy get pods` is Ready. If it crash-loops, read `kubectl -n egress-proxy logs deploy/squid`: likely causes are the non-root user (uid 13), the read-only root filesystem, or the `squid -N` command.
2. Allowed: `kubectl -n hermes exec deploy/hermes -c hermes -- curl -sS -o /dev/null -w '%{http_code}\n' -x http://squid.egress-proxy.svc:3128 https://api.github.com/rate_limit` returns 200 (without a token, a 200 or 403 from GitHub both prove the tunnel works).
3. Denied: the same with `https://example.com` returns a proxy error (403).
4. No bypass: `curl -m 5 https://api.github.com` from the hermes pod without `-x` times out.
5. Other callers: from another namespace the proxy is refused (RBAC denied by `squid-from-hermes`).
6. `kubectl -n egress-proxy logs deploy/squid` shows the allowed and denied requests.
7. Mesh enrolment: if step 2 fails with a refused HBONE connection, delete the squid pod (see "Restart recovery" in `deploy/istio/README.md`).

## Port 3129 and the Discord hosts: not yet verified (2026-11-18)

Written and reviewed, not run. `squid -k parse` and the allow and deny checks for both listeners still have to run (Docker was unresponsive when this was written), then the in-cluster checks above repeated for `:3129`: allowed `https://example.com`, denied a 10.x address, denied from another namespace. Spec 15 lists them as acceptance criteria. For Discord, watch the Squid log on first connect: the gateway may use a host under `.discord.gg` other than `gateway.discord.gg`.
