# Specter Knowledge Base

| slug | title | summary | tags | path |
|------|-------|---------|------|------|
| ollama-server-configuration | Ollama Server Configuration | Environment variables for Ollama (context, keep-alive, queue, KV cache, models path, no-cloud) and how to set them under systemd or Kubernetes | ollama, configuration, environment-variables, spec-02 | ollama/server-configuration.md |
| ollama-concurrency-and-vram | Ollama Concurrency, Model Swapping and VRAM | How Ollama queues, swaps and parallelises models, and what that means for a 16GB GPU | ollama, vram, concurrency, kv-cache, spec-02, spec-09 | ollama/concurrency-and-vram.md |
| hermes-custom-endpoints-and-ollama | Hermes Agent: Custom Endpoints, Ollama and Context Length | Configuring Hermes with an OpenAI-compatible endpoint (LiteLLM/Ollama), context-length pinning and tool-calling requirements | hermes, providers, ollama, litellm, spec-04 | hermes/custom-endpoints-and-ollama.md |
| k3s-containerd-and-nvidia-runtime | k3s: containerd Config, NVIDIA Runtime and Host Prep | NVIDIA runtime detection, RuntimeClass, containerd templates, systemd install and WSL2 DNS notes for k3s | k3s, containerd, nvidia, gpu, spec-01 | platform/k3s-containerd-and-nvidia-runtime.md |
| istio-ambient-on-k3s | Istio Ambient Mode on k3s: Platform Prerequisites | Use global.platform=k3s for istio-cni on bundled flannel; custom CNI path overrides; what the page does not verify for WSL2 | istio, ambient, k3s, cni, spec-08 | mesh/istio-ambient-on-k3s.md |
| litellm-proxy-deployment-and-routing | LiteLLM Proxy: Deployment, Ollama Routing, Keys, Timeouts, Metrics | Ollama model_list aliases, DB-dependent features, probes, timeouts/retries and Prometheus metrics for the LiteLLM proxy | litellm, gateway, ollama, prometheus, spec-09 | litellm/proxy-deployment-and-routing.md |
| litellm-mcp-gateway | LiteLLM MCP Gateway: Registering Servers and Per-Key Tool Access | Registering MCP servers and restricting tools per virtual key via object_permission | litellm, mcp, browser, spec-09 | litellm/mcp-gateway.md |
| dcgm-exporter | NVIDIA DCGM Exporter for GPU Metrics | DCGM exporter metrics, Helm chart settings and the WSL2/GeForce caveat with nvidia-smi fallback | dcgm, gpu, prometheus, spec-06 | observability/dcgm-exporter.md |
