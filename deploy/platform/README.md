# deploy/platform

Cluster foundation delivered first by Flux (spec 10, `platform` stage): workload namespaces (`ollama`, `openviking`, `hermes`, plus `nvidia-device-plugin`), `RuntimeClass nvidia`, and the NVIDIA device plugin as a pinned `HelmRelease`.

The device plugin runs with `runtimeClassName: nvidia` and `affinity: null` (the chart's default affinity needs NFD labels that do not exist here). GPU pods must set `runtimeClassName: nvidia` and request `nvidia.com/gpu: 1`.

The default `local-path` StorageClass is provided by k3s and is not redeclared here.

`tests/` holds the GPU and PVC smoke tests used by `scripts/30-verify.sh`; it is not part of this Kustomization.
