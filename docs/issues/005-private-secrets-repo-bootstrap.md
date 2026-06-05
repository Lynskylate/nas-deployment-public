# [Migration] Bootstrap A Private Secrets Repository For Platform And App Runtime Secrets

## Summary

Create and maintain a dedicated private GitHub repository to hold encrypted infrastructure and application secrets for the K3s migration.

This issue tracks the completed transition from temporary repo-managed plaintext/bootstrap secrets toward a reviewable encrypted source of truth, plus the follow-up hardening work that remains.

## Problem

The initial migration bootstrap temporarily allowed a plaintext `k3s_cluster_token` in the infrastructure repo so GitHub Actions could keep moving.

That bootstrap is now replaced by:

- public repo: `nas-deployment-public`
- private repo: `nas-deployment-vault`
- encryption: `sops + age`
- deploy flow: checkout vault repo -> decrypt bootstrap/apply-time values -> render runtime overlays -> run Ansible

That is acceptable only as a short-lived migration step. Long term we need:

- a stable source of truth outside node-local files
- reviewable secret changes through Git history
- no permanent plaintext secrets in `nas-deployment`
- a path for Argo CD and app deployments to consume the same managed secret source

## Scope

- Create a private GitHub repository for encrypted secrets
- Define directory/file conventions for platform and app secrets
- Adopt `sops + age` for encryption
- Move K3s bootstrap secrets into the new repository
- Move Argo CD bootstrap/repo credentials into the new repository
- Document how GitHub Actions reads and decrypts required values
- Define the follow-up integration path for Argo CD / Sealed Secrets

## Out Of Scope

- Full application secret migration for every service
- External Secrets Operator adoption
- Vault / cloud secret manager adoption
- Final RBAC design inside Kubernetes

## Acceptance Criteria

- A private repository exists for managed encrypted secrets
- `k3s_cluster_token` is moved out of plaintext repo config into an encrypted file
- GitHub Actions can decrypt the needed bootstrap values during deployment
- `nas-deployment-public` documents the secret source and decryption flow
- Future app/runtime secrets have a documented location and naming convention

## PR Linking

- Suggested PR title: `feat: bootstrap private secrets repository flow`
- GitHub issue: `#8`
- PR body should include: `Closes #<issue-number>`
- Planning doc path: `docs/issues/005-private-secrets-repo-bootstrap.md`
