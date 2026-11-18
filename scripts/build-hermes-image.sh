#!/bin/bash
# Build the custom Hermes image (deploy/hermes/image/Dockerfile) and load it into k3s containerd. There is no registry:
# hermes.yaml uses imagePullPolicy IfNotPresent with this local tag. Usage: build-hermes-image.sh [CLAUDE_CODE_VERSION]
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${HERMES_IMAGE:-dsm-shai/hermes:v0.23.1-1}"      # keep in step with hermes.yaml
docker build -t "$TAG" --build-arg "CLAUDE_CODE_VERSION=${1:-latest}" deploy/hermes/image
docker save "$TAG" | sudo k3s ctr images import -
echo "loaded $TAG; roll it out with: kubectl -n hermes rollout restart deploy/hermes"
