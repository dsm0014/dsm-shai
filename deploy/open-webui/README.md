# deploy/open-webui

Open WebUI (spec 05), namespace `open-webui`. Host name `open-webui.localhost`, routed by the Istio ingress gateway. Status: **working through ingress**; the Istio ingress policy and the egress NetworkPolicy (cluster DNS, LiteLLM on port 4000 and the HBONE tunnel only) are deployed, and only the live blocked-path test and the LAN and Windows checks remain (step 11).

## Image

`ghcr.io/open-webui/open-webui:v0.13.3@sha256:46b59158e6558eeb980bc828e0f1b30238ad24d82ed84d5e5eda1dab2a082f14` (upstream release 2026-11-08). The upstream Dockerfile defaults to UID 0; this deployment runs as UID 1000 (`runAsNonRoot`) and the app works with a writable PVC.

## Configuration

- `OPENAI_API_BASE_URL=http://litellm.litellm.svc:4000/v1`, key from `open-webui-secrets` (virtual key `open-webui`, allowlist `chat` and `vision`, budget 20, 120 rpm). `/api/models` lists only those two.
- Ollama is not used directly (`ENABLE_OLLAMA_API=False`). No cloud model endpoint.
- `WEBUI_AUTH=True`, `ENABLE_SIGNUP=False`: the first account becomes admin, and later signups return 403. `WEBUI_SECRET_KEY` is from the same Secret.
- `ENABLE_WEB_SEARCH=False`: the SearXNG decision is **skip** (the spec default). No SearXNG resources exist.
- `OFFLINE_MODE=True` and telemetry off: no model downloads or analytics.
- Data: PVC `open-webui-data` (10Gi, `local-path`, WSL ext4) at `/app/backend/data`. Chat history and the account survive a pod restart (verified: `webui.db` kept).

## Ingress

- `Gateway open-webui` (selector `istio: ingressgateway`, HTTP port 80, host `open-webui.localhost`) and `VirtualService open-webui` routing to `open-webui.open-webui.svc.cluster.local:8080`. Only Open WebUI is routed. Ollama, OpenViking, LiteLLM and Hermes have no Ingress, Gateway or VirtualService and are ClusterIP only.
- The `istio-ingressgateway` Service stays ClusterIP. To reach it from the host, run a loopback port-forward:

  ```sh
  kubectl -n istio-system port-forward svc/istio-ingressgateway 8080:80
  # then open http://open-webui.localhost:8080 (browsers resolve *.localhost to 127.0.0.1)
  ```

  `kubectl port-forward` listens on 127.0.0.1 only, so the gateway is not on a LAN interface. The Windows browser reaches it through WSL2 localhost forwarding. Note: this needs a running port-forward process; a persistent host listener would need a different mechanism and is not set up.

## Verification (done, 2026-11-16, through the ingress)

| Check | Result |
|---|---|
| Login page via `Host: open-webui.localhost` | 200 HTML |
| First signup | 200, role `admin` |
| Second signup | 403 |
| Sign-in | token issued |
| `/api/models` | `chat`, `vision` (from LiteLLM) |
| Chat completion, model `chat` | `OK` (routed through LiteLLM to Ollama) |
| Pod restart | database kept; the app comes back Ready |
| Service types | all ClusterIP; no NodePort, LoadBalancer or hostPort in these namespaces |

## Not yet verified (step 11, spec 08 part B)

- The egress NetworkPolicy now exists, so the pod network is no longer open. The live test that, from the Open WebUI pod, LiteLLM and DNS are allowed while direct Ollama, arbitrary external IPs and other in-cluster services are blocked is still to run.
- Unreachable from another LAN host: needs a second device.
- Windows browser test: not run from this session.

## Teardown

```sh
kubectl delete -k deploy/open-webui          # keeps the PVC
kubectl -n open-webui delete pvc open-webui-data   # removes chat history and accounts
```
