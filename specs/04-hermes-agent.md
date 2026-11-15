# Spec 04 — Hermes Agent

**Status:** TODO

## Purpose
Run Hermes Agent (NousResearch/hermes-agent, MIT) in the k3s namespace `hermes`, using in-cluster Ollama for inference and OpenViking as persistent memory, knowledge and skills storage. Hermes runs under tight autonomy boundaries so it can safely write reusable skills from completed tasks. Depends on spec 01 (cluster), spec 02 (inference) and spec 03 (OpenViking).

## Behavior

**Image**
- The image is built from a Dockerfile in `deploy/hermes/`. The Hermes version is pinned through a build arg (release tag or commit SHA), and the base image is pinned by tag or digest.
- The upstream install script (`install.sh`) may be run only at build time, against the pinned version. Nothing is fetched with `curl | bash` at container start.
- The image runs as a non-root UID/GID, and that user owns `~/.hermes` and the workspace.
- The image is imported into k3s (`k3s ctr images import` or a local registry), and the Deployment uses `imagePullPolicy: IfNotPresent`.

**Configuration**
- `config.yaml` is delivered by a ConfigMap. An init container or entrypoint copies it into `~/.hermes/config.yaml` on each start, so the ConfigMap stays the source of truth.
- The model provider is a custom OpenAI-compatible endpoint with base URL `http://ollama.ollama.svc:11434/v1` and model `qwen3:14b`. No API key is used; if Hermes requires a non-empty value, a dummy placeholder is used and no Secret is created.
- The Hermes context length is set to 32768, matching `OLLAMA_CONTEXT_LENGTH` from spec 02. The ConfigMap comments name that coupling, so a change to one is made to the other.
- OpenViking (`http://openviking.openviking.svc`) is configured as the memory, knowledge and skills backend. It is wired through MCP if Hermes supports it, and through the closest supported integration (HTTP tool or skill) otherwise. The chosen path is documented in `deploy/hermes/README.md`.

**Storage**
- `~/.hermes` lives on a PVC on the WSL ext4 volume (local-path StorageClass, not `/mnt/c`). It holds config, sessions and locally generated skills, and survives pod restarts and image upgrades.
- A separate bounded workspace volume (PVC or `emptyDir` with `sizeLimit`, e.g. 10Gi) is the agent's working directory.
- There are no `hostPath` mounts and no access to the Docker or containerd socket.

**Safety boundaries**
- The pod runs as non-root with `runAsNonRoot`, `allowPrivilegeEscalation: false`, all capabilities dropped, `seccompProfile: RuntimeDefault`, and a read-only root filesystem where feasible. Writable paths are only `~/.hermes`, the workspace and `/tmp`.
- A dedicated ServiceAccount is used with `automountServiceAccountToken: false` and no RoleBindings. The pod has no cluster-admin credentials.
- A default-deny NetworkPolicy covers ingress and egress. Egress is allowed only to the following:
  - Ollama in namespace `ollama` on 11434.
  - OpenViking in namespace `openviking` on its service port.
  - kube-dns on 53 UDP/TCP.
  - An explicit web allowlist (for example `github.com` and package registries), kept in a documented, editable manifest.
- The web allowlist is enforced with a mechanism that works on k3s. Plain NetworkPolicy cannot match on hostnames, so the implementation chooses either an egress proxy with a domain allowlist or Cilium FQDN policies, and records the choice in `deploy/hermes/README.md`. Direct egress to other destinations is blocked.
- CPU and memory requests and limits are set on the container (e.g. 500m/2Gi requests, 2 CPU/4Gi limits). The workspace is size-bounded.

**Operation**
- Interactive mode: `kubectl -n hermes exec -it deploy/hermes -- hermes` (or `attach`) opens a session with the persisted config.
- Headless mode: the Deployment (one replica, `Recreate` strategy) runs Hermes as a long-lived process that survives disconnects. Its logs are readable via `kubectl logs`. The pod restarts on failure and resumes with state from `~/.hermes`.
- A readiness and liveness check confirms the process is alive and that Ollama and OpenViking are reachable.

## Acceptance Criteria
- [ ] The image builds from the repo with a pinned Hermes version, and no network fetch of install scripts occurs at runtime.
- [ ] Pod `hermes` is Running in namespace `hermes`, with `~/.hermes` on a PVC backed by the WSL ext4 volume.
- [ ] `~/.hermes/config.yaml` matches the ConfigMap and shows Ollama `/v1`, `qwen3:14b` and context length 32768.
- [ ] Deleting the pod preserves `~/.hermes` contents (sessions, skills) after the replacement starts.
- [ ] `kubectl auth can-i --list` from inside the pod shows no cluster permissions, and no token exists at `/var/run/secrets/kubernetes.io`.
- [ ] The container runs as a non-root user with no extra capabilities and no `hostPath` volumes, and resource limits are set.
- [ ] From the pod, Ollama, OpenViking and an allowlisted web host are reachable. An arbitrary non-allowlisted host and the Kubernetes API are not.
- [ ] An interactive session via `kubectl exec -it` responds using `qwen3:14b` served by Ollama.
- [ ] Headless mode keeps running after the exec session disconnects, and `kubectl logs` shows activity.
- [ ] End-to-end check: a prompt such as "create a file in the workspace listing the 3 largest files in it, then summarize" makes Hermes call a tool and produce the file in the bounded workspace.
- [ ] After that task, a memory, knowledge or skill item is present in OpenViking. This is confirmed by querying the OpenViking API or CLI from outside the Hermes pod and finding an item attributable to the task.
- [ ] A second session retrieves that item from OpenViking, showing persistence beyond the first session's context.
- [ ] `deploy/hermes/README.md` documents the build, pin-bump, deploy, OpenViking integration path, web-allowlist mechanism, and how to drive the agent.
