# Specter Knowledge Base

| slug | title | summary | tags | path |
|------|-------|---------|------|------|
| ollama-server-configuration | Ollama Server Configuration | Environment variables for Ollama (context, keep-alive, queue, KV cache, models path, no-cloud) and how to set them under systemd or Kubernetes | ollama, configuration, environment-variables, spec-02 | ollama/server-configuration.md |
| ollama-concurrency-and-vram | Ollama Concurrency, Model Swapping and VRAM | How Ollama queues, swaps and parallelises models, and what that means for a 16GB GPU | ollama, vram, concurrency, kv-cache, spec-02, spec-09 | ollama/concurrency-and-vram.md |
| hermes-custom-endpoints-and-ollama | Hermes Agent: Custom Endpoints, Ollama and Context Length | Configuring Hermes with an OpenAI-compatible endpoint (LiteLLM/Ollama), context-length pinning and tool-calling requirements | hermes, providers, ollama, litellm, spec-04 | hermes/custom-endpoints-and-ollama.md |
| k3s-containerd-and-nvidia-runtime | k3s: containerd Config, NVIDIA Runtime and Host Prep | NVIDIA runtime detection, RuntimeClass, containerd templates, systemd install and WSL2 DNS notes for k3s | k3s, containerd, nvidia, gpu, spec-01 | platform/k3s-containerd-and-nvidia-runtime.md |
