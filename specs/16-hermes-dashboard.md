# Spec 16 — Hermes Dashboard Exposure

**Status:** TODO

## Purpose

Give the owner the Hermes Agent web dashboard (config, API keys, sessions, cron and kanban views) at `http://hermes.localhost`, host-local only, behind password authentication. The pod today runs Hermes headless: the dashboard command exists (`hermes dashboard`) but its web assets are not built in the image and nothing exposes it. Depends on specs 04 (Hermes), 05 (ingress pattern), 07 (secrets), 08 (mesh) and 12 (custom image).

## Behavior

**Amendment to spec 05 (recorded here, and in spec 05 in the same PR)**
- Spec 05 says Hermes is never referenced by an ingress route and that only Open WebUI and Grafana are exposed. This spec adds one exception: the Hermes dashboard, `hermes.localhost` only, on the existing Istio ingress gateway. Nothing else in the `hermes` namespace is routed (not the gateway API port, not the metrics exporter). Hermes's other Services stay ClusterIP, and the gateway stays host-local (no NodePort, no LAN bind).

**Dashboard process**
- A second container `dashboard` in the hermes pod, same custom image (spec 12) and user 10000, running `hermes dashboard --host 0.0.0.0 --port 9119 --no-open --skip-build`. It uses the same `home` PVC as the agent, because it edits the agent's config, keys and sessions. It does not get the swarm, nightly or Claude token environment: only the variables the dashboard needs.
- The web UI is built at image build time, never at runtime: `deploy/hermes/image/Dockerfile` gets a stage (Node and pnpm, network at build time only) that builds the dashboard frontend from the pinned upstream source, and the result is copied to a read-only path set by `HERMES_WEB_DIST`. The pod has no pnpm and no registry access, so the runtime path is `--skip-build`. `scripts/build-hermes-image.sh` and the tag are bumped together with `hermes.yaml`.
- Probes: HTTP liveness and readiness on `/` or the dashboard's health path. Resource requests and limits are modest (it must not starve Ollama).

**Authentication (required, fail closed)**
- Hermes refuses a non-loopback bind without an auth provider. This spec uses the bundled password provider: `HERMES_DASHBOARD_BASIC_AUTH_USERNAME`, `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` (never a plaintext password) and `HERMES_DASHBOARD_BASIC_AUTH_SECRET` (a stable session secret), delivered from a SOPS Secret `deploy/secrets/hermes-dashboard.sops.yaml` (ciphertext only, scanned by `scripts/check-sops.sh`) through `secretKeyRef`. A script `scripts/set-dashboard-password.sh` reads the password silently, hashes it with Hermes's own `hash_password`, generates the session secret, and writes the encrypted file; it never prints either value.
- `HERMES_DASHBOARD_PUBLIC_URL` (or the equivalent `dashboard.public_url`) is set to `http://hermes.localhost` only if the dashboard requires it behind the proxy; the spec records the final choice after testing.
- The dashboard can read and change Hermes's config and API keys, so: sign-in rate limiting and session TTL are left at the upstream defaults or tightened, never loosened, and the README states that the dashboard is as powerful as a shell in the pod.

**Mesh and network**
- `Gateway` and `VirtualService` for `hermes.localhost` (same shape as Grafana and Open WebUI) route to a new ClusterIP Service `hermes-dashboard` on port 9119 only.
- An Istio `AuthorizationPolicy` allows port 9119 only from the ingress gateway's service account. The existing hermes default-deny remains, and the NetworkPolicy permits the gateway to reach 9119. No other namespace or pod can reach the dashboard.
- Egress is unchanged (the dashboard uses the same proxy-only egress; it gets no new hosts).

**Documentation**
- `deploy/hermes/README.md` documents how to set the password, how to reach the UI (`hermes.localhost` through the same loopback port-forward as Open WebUI and Grafana), what the dashboard can do, how to rotate the password and how to take it down (scale the container out by removing it from the manifest; there is no in-cluster switch).

## Acceptance Criteria

- [ ] The custom image contains the built dashboard assets (`HERMES_WEB_DIST` exists and is non-empty) and the `dashboard` container starts with `--skip-build`, without network access.
- [ ] `deploy/secrets/hermes-dashboard.sops.yaml` is ciphertext only, `scripts/check-sops.sh` passes, and neither the password nor its hash appears in a manifest, ConfigMap, log or the repository.
- [ ] Without credentials, the dashboard returns the login page or 401 for every route (checked with curl through the gateway); a wrong password is rejected; the right password opens the UI.
- [ ] From Windows (or a loopback port-forward), `http://hermes.localhost` loads the dashboard login, then the dashboard, through the Istio ingress gateway. A second LAN device cannot reach it.
- [ ] From another namespace or from a pod in `hermes` other than the gateway path, port 9119 is unreachable (mesh deny and NetworkPolicy); only the ingress gateway can reach it.
- [ ] The dashboard shows live data from the PVC (sessions and config) and an edit made in it is visible to the agent; the swarm, nightly job and the Claude token are not exposed to the dashboard container's environment.
- [ ] Only `hermes.localhost` is routed for the `hermes` namespace: `kubectl get virtualservice,gateway -A` shows no other Hermes route, and the Hermes Services other than `hermes-dashboard` are unchanged.
- [ ] Spec 05 carries the exception, and `deploy/hermes/README.md` documents setup, access, rotation and removal.
