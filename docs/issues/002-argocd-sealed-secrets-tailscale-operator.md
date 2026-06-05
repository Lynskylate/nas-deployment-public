# [Migration] Install Argo CD, Sealed Secrets, And Tailscale Operator

## Summary

Install the GitOps control plane and secret/network operators required by the target architecture.

## Problem

After K3s exists, the platform still lacks:

- Argo CD as the application reconciler
- Sealed Secrets as the runtime secret delivery mechanism
- Tailscale Operator as the tailnet ingress and API proxy layer

Without these platform components, application repositories cannot self-manage Helm/resources in the desired model.

## Scope

- Install Argo CD on K3s
- Install Sealed Secrets controller
- Install Tailscale Kubernetes Operator
- Bootstrap repo access secrets for Argo CD
- Expose Argo CD and future platform ingress over tailnet
- Add platform docs and verification commands

## Out Of Scope

- Business application Helm charts
- corp-finance-monitor data cutover
- shared storage beyond local PVC

## Acceptance Criteria

- Argo CD is reachable from the tailnet
- Sealed Secrets controller can unseal a test secret in-cluster
- Tailscale Operator can expose a test workload to the tailnet
- Argo CD does not require access to runtime plaintext application secrets
- Platform bootstrap remains owned by `nas-deployment`

## PR Linking

- Suggested PR title: `feat: bootstrap argocd and platform operators`
- GitHub issue: `#4`
- PR body should include: `Closes #4`
- Planning doc path: `docs/issues/002-argocd-sealed-secrets-tailscale-operator.md`
