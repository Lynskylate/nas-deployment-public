# [Migration] Bootstrap K3s Platform On GTR + Edge Nodes

## Summary

Migrate the host runtime baseline from `rootless Podman + systemd user services` toward `K3s` as the new application runtime platform.

This issue covers only the cluster bootstrap layer:

- `gtr` as the single K3s server
- `aliyun` and `tencent` as K3s agents
- host prerequisites and repeatable Ansible deployment
- validation playbooks and operator-facing documentation

## Problem

The current platform assumes:

- application deployments are pushed over SSH
- runtime state is expressed as Podman/systemd units
- `gtr-release-config` owns rollout execution

That model does not fit the target architecture where:

- applications manage their own Helm/resources
- Argo CD performs reconciliation
- `nas-deployment` owns the cluster/platform baseline

## Scope

- Add K3s prerequisite role(s)
- Add K3s server role for `gtr`
- Add K3s agent role for `aliyun` and `tencent`
- Add deploy/verify playbooks
- Add repo documentation for manual bootstrap
- Add PR syntax validation coverage
- Wire the bootstrap into GitHub Actions infra deployment
- Consume the K3s bootstrap token from the dedicated private secrets repository during deployment

## Out Of Scope

- Argo CD installation
- Sealed Secrets installation
- Tailscale Operator installation
- application migration
- data migration

## Acceptance Criteria

- `ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-platform.yml` is available
- `ansible-playbook -i inventory-edge.ini verify-gtr-k3s-platform.yml` is available
- K3s server is configured to use the host Tailscale network path
- Built-in `traefik` and `servicelb` are disabled
- Required platform CIDRs are explicitly configured and documented
- PR validation checks include the new playbooks
- `deploy-infra.yml` can run the K3s bootstrap after decrypting the required secret overlays from the private vault repository
- The public repo does not store the bootstrap token in tracked plaintext files

## PR Linking

- Suggested PR title: `feat: bootstrap k3s platform baseline`
- GitHub issue: `#3`
- PR body should include: `Closes #3`
- Planning doc path: `docs/issues/001-k3s-platform-bootstrap.md`
