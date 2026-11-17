# Egress proxy for the Hermes nightly job (spec 11)

The hermes pod has no direct internet route (`deploy/hermes/egress-networkpolicy.yaml`). The nightly job reaches GitHub through a Squid forward proxy in namespace `egress-proxy`, port 3128. Used by the job wrapper only (`NIGHTLY_HTTPS_PROXY`); interactive Hermes is not proxied.

- **Allowlist:** CONNECT on 443 to `github.com`, `api.github.com`, `codeload.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`. Everything else gets 403 and is logged. Edit `squid.conf`.
- **Who may call it:** AuthorizationPolicy `squid-from-hermes` allows only `cluster.local/ns/hermes/sa/hermes` on 3128 (deny-all baseline). The proxy's own egress is limited to DNS and port 443 on public addresses (`squid-egress`).
- **Why a proxy:** `outboundTrafficPolicy: REGISTRY_ONLY` is not enforced by ambient ztunnel (`deploy/istio/README.md`), and a NetworkPolicy cannot match hostnames.
- **Flux:** stage `egress` (`clusters/dsm-shai/egress.yaml`, dependsOn `platform` and `istio`); the `hermes` stage dependsOn it.
- **Deviation from the spec:** the spec asked for SNI inspection (`ssl_bump peek` and `splice`). That needs an OpenSSL build of Squid and the pinned Ubuntu image is probably GnuTLS, so the allowlist is on the CONNECT target. Squid dials the allowed host itself, so a different SNI still only reaches GitHub. Use a `squid-openssl` image and add `ssl_bump` rules if SNI checking is wanted.

## Verified locally (Docker, 2026-11-17) and what is still open

Run in Docker with the pod's restrictions (uid 13, read-only root with tmpfs on `/tmp`, `/var/spool/squid`, `/var/log/squid`, `/var/run`, all capabilities dropped): `squid -k parse` accepts `squid.conf` (one warning, `HTTP requires the use of Via`, from `via off`); the process starts; CONNECT to `api.github.com:443` tunnels (200); CONNECT to `example.com:443`, a plain `http://github.com` request and `github.com:8443` are all refused (403, logged `TCP_DENIED`). The image's Squid is built `--with-gnutls`, so `ssl_bump` is not available (confirmed). **Not yet verified in the cluster:** the pod starting under the mesh, the AuthorizationPolicy and the NetworkPolicy. Use the list below.

## Verify before use (in the cluster)

1. `kubectl -n egress-proxy get pods` is Ready. If it crash-loops, read `kubectl -n egress-proxy logs deploy/squid`: likely causes are the non-root user (uid 13), the read-only root filesystem, or the `squid -N` command.
2. Allowed: `kubectl -n hermes exec deploy/hermes -c hermes -- curl -sS -o /dev/null -w '%{http_code}\n' -x http://squid.egress-proxy.svc:3128 https://api.github.com/rate_limit` returns 200 (without a token, a 200 or 403 from GitHub both prove the tunnel works).
3. Denied: the same with `https://example.com` returns a proxy error (403).
4. No bypass: `curl -m 5 https://api.github.com` from the hermes pod without `-x` times out.
5. Other callers: from another namespace the proxy is refused (RBAC denied by `squid-from-hermes`).
6. `kubectl -n egress-proxy logs deploy/squid` shows the allowed and denied requests.
7. Mesh enrolment: if step 2 fails with a refused HBONE connection, delete the squid pod (see "Restart recovery" in `deploy/istio/README.md`).
