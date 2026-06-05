# Project Runtime Baseline

This directory documents the host baseline required for the new release flow.

The host is responsible only for shared runtime capability:

- rootless Podman packages
- shared directories under `/srv`
- helper scripts for inspection and verification

Business-project deployment now happens from the release-config repository. Project repositories no longer carry host-level Ansible or systemd deployment logic.

## Goals

- Install the packages needed for rootless Podman on `gtr`
- Create shared roots:
  - `/srv/projects`
  - `/srv/project-secrets`
  - `/srv/project-state`
- Install `/usr/local/bin/project-runtime-report` for quick inspection

## Deploy

```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-project-runtime.yml
```

## Verify

```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini verify-gtr-project-runtime.yml
```

## Boundaries

- Image rollout is triggered by the release-config repository.
- Project repositories do not SSH to `gtr` directly.
- Tailscale and Envoy exposure stay in the infrastructure repository and remain separately reviewed.
