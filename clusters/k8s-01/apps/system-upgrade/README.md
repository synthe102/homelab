# Talos and Kubernetes upgrades

[tuppr](https://github.com/home-operations/tuppr) runs in `system-upgrade` and
reconciles the cluster-scoped `TalosUpgrade/talos` and
`KubernetesUpgrade/kubernetes` resources in `plans/configs/`. Renovate tracks
their version fields. Talos upgrades run one node at a time, wait for CSI volume
detach before rebooting, and require all nodes to be Ready. Kubernetes upgrades
also require Ready nodes; tuppr serializes the two upgrade types cluster-wide.

The existing Talos machine configuration already permits `os:admin` API access
from this namespace. The chart creates its Kubernetes RBAC and Talos service
account. tuppr discovers each node's installer image and schematic, preserving
the configured Image Factory Secure Boot installer and extensions. It selects
the job's `talosctl` version from the running Talos version.

## Migration from system-upgrade-controller

The Argo Application names remain `system-upgrade-controller` and
`system-upgrade-plan` deliberately: the root Application does not automatically
prune removed child Applications. Reusing their identities lets their existing
prune policies remove the old Deployment, service accounts, cluster-admin
binding, and namespaced `upgrade.cattle.io` Plans. The Helm release and new
Deployment are named `tuppr`.

The new Deployment uses sync wave 1, after the old controller is pruned in wave
0. The plans Application retries while the separately managed tuppr CRDs and
admission webhook become available. Server-side apply handles the large CRDs;
scoped ignore rules preserve tuppr-managed webhook certificates and CA bundles.

Before merging, check that there are no active jobs from the previous controller:

```sh
kubectl -n system-upgrade get plans.upgrade.cattle.io,jobs,pods
```

The migration keeps the existing targets: Talos `v1.13.9` and Kubernetes
`v1.37.0`. At preparation time (2026-09-03), all three nodes were on Talos
`v1.13.9` / Kubernetes `v1.36.4`, and the old Kubernetes plan had failed with
`BackoffLimitExceeded`. No upgrade jobs remained. Deploying this migration will
therefore retry the pending Kubernetes upgrade under tuppr.

After Argo sync, verify the old Deployment and Plans are gone, and inspect the
new resources and their actual upgrade status:

```sh
kubectl -n argocd get applications system-upgrade-controller system-upgrade-plan
kubectl -n system-upgrade get deployments,pods,jobs
kubectl -n system-upgrade get plans.upgrade.cattle.io
kubectl get talosupgrade talos
kubectl get kubernetesupgrade kubernetes
kubectl describe talosupgrade talos
kubectl describe kubernetesupgrade kubernetes
kubectl -n system-upgrade logs deployment/tuppr --all-pods=true --tail=100
kubectl get nodes -o wide
```

The old `plans.upgrade.cattle.io` CRD and node plan labels are not managed by
these Applications; leaving them present does not execute upgrades. Remove them
separately only after confirming there are no remaining consumers.

For future upgrades, edit the version fields through GitOps and follow Talos's
supported minor-version upgrade sequence. See tuppr's
[operations guide](https://github.com/home-operations/tuppr/blob/0.5.2/docs/operations.md)
for suspension and retry annotations.
