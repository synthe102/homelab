# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

GitOps-driven Kubernetes homelab running on Talos Linux with ArgoCD for continuous deployment. Single cluster (`k8s-01`) on an Intel NUC.

## Architecture

### GitOps Flow

All cluster state is declared in YAML and synced via ArgoCD. A **root Application** (`clusters/k8s-01/apps/root/app.yaml`) points at `clusters/k8s-01/apps/` and auto-syncs all child applications with self-healing enabled.

### Application Layout

Each app lives under `clusters/k8s-01/apps/<category>/<app-name>/` with:
- `app.yaml` — ArgoCD Application CR (Helm chart source with inline `valuesObject`, or Git source)
- `kustomization.yaml` — Kustomize resource list
- `configs/` — supporting resources (ExternalSecrets, HTTPRoutes, NetworkPolicies, etc.)

Categories group related apps: `monitoring/`, `media/`, `home-automation/`, `game-servers/`, `downloads/`, etc. The top-level `clusters/k8s-01/apps/kustomization.yaml` lists all categories.

### Key Infrastructure Components

- **Secret management**: External Secrets Operator pulling from BitWarden via `ClusterSecretStore` named `bitwarden-homelab`. Secrets use naming convention `K8S_01_<NAMESPACE>_<SECRET_NAME>`.
- **Networking**: Cilium with Gateway API. HTTPRoutes reference a gateway named `internal` in `kube-system`. Domain: `*.k8s-01.suslian.engineer`.
- **Auth**: Authentik as OIDC provider at `auth.suslian.engineer`, integrated with Grafana, ArgoCD, and other services.
- **Storage**: Rook/Ceph for distributed storage.
- **Monitoring**: Prometheus (via kube-prometheus-stack) -> Mimir (long-term), Loki (logs), Pyroscope (profiling), Grafana (dashboards).
- **Terraform**: OpenTofu stacks under `clusters/k8s-01/terraform/stacks/` for Authentik provider configuration.

### Helm Values Pattern

Most apps are deployed as Helm charts with values inlined directly in the ArgoCD Application `spec.sources[].helm.valuesObject`. This means Helm values live inside `app.yaml`, not in separate `values.yaml` files.

## Development Environment

Uses [devenv](https://devenv.sh/) (Nix-based) with direnv integration. Enter the dev shell automatically via `direnv allow` or manually via `devenv shell`.

### Available Tools (via devenv)

`talosctl`, `clusterctl`, `just`, `k9s`, `cilium-cli`, `argocd`, `bws`, `velero`, `kopia`, `kubevirt`, `kind`, `vcluster`, `opentofu`, `uv`, `golangci-lint`

### YAML Formatting

yamlfmt runs as a pre-commit git hook (configured in `devenv.nix`). Config in `.yamlfmt.yaml`:
- Formatter type: `basic`
- Document start markers (`---`) are required

All YAML files must pass yamlfmt before committing.

## CI/CD

- **ArgoCD Diff Preview**: GitHub Actions workflow (`.github/workflows/argocd-diff.yaml`) runs on PRs to `main`, spins up a Kind cluster, and posts rendered ArgoCD diffs as PR comments. Runner: `gha-runner-synthe102-homelab` (self-hosted).
- **Renovate**: Auto-updates dependencies. Patch/minor versions auto-merge. Talos and KubeVirt major updates require manual approval. Custom regex manager handles YAML-annotated deps (`# renovate: datasource=... depName=...`).

## Common Patterns

### Adding a New Application

1. Create `clusters/k8s-01/apps/<category>/<app-name>/app.yaml` with ArgoCD Application CR
2. Create `clusters/k8s-01/apps/<category>/<app-name>/kustomization.yaml` listing resources
3. Add any configs (ExternalSecrets, HTTPRoutes) under a `configs/` subdirectory
4. Add the app to `clusters/k8s-01/apps/<category>/kustomization.yaml`
5. If it's a new category, also add it to `clusters/k8s-01/apps/kustomization.yaml`

### Renovate-Tracked Dependencies

For dependencies tracked via YAML annotations, use the comment format:
```yaml
# renovate: datasource=github-releases depName=org/repo
version: v1.2.3
```
