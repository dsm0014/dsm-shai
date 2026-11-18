# Custom Hermes image (spec 12). Base is the pinned upstream Hermes image; add anything the pod needs here so nothing is
# downloaded at runtime. Build and load into k3s with scripts/build-hermes-image.sh. Bump HERMES_BASE and CLAUDE_CODE_VERSION together with hermes.yaml.
ARG HERMES_BASE=docker.io/nousresearch/hermes-agent:v0.23.1@sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08

# Stage 1: fetch the Claude Code CLI with a full Node toolchain (build time only; the pod has no registry access).
FROM docker.io/library/node:22-bookworm-slim AS claude-cli
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g --prefix /opt/claude "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && /opt/claude/bin/claude --version

# Stage 2: upstream Hermes plus the CLI. Runs as the same user (10000) as upstream.
FROM ${HERMES_BASE}
COPY --from=claude-cli /opt/claude /opt/claude
ENV CLAUDE_BIN=/opt/claude/bin/claude \
    DISABLE_AUTOUPDATER=1
# Fail the build if the CLI cannot start with the base image's own runtime.
RUN /opt/claude/bin/claude --version
