#!/usr/bin/env bash
set -euo pipefail

rm -rf .vault/repo
rm -f edge/ansible/group_vars/all/secret.runtime.yml
rm -f edge/ansible/group_vars/all/github-token.runtime.yml
rm -f edge/ansible/host_vars/gtr/secret.runtime.yml
rm -f edge/ansible/host_vars/aliyun/secret.runtime.yml
rm -f mihomo/ansible/group_vars/all/secret.runtime.yml
rm -f mihomo/ansible/group_vars/aliyun/secret.runtime.yml
rm -f grafana/secret.runtime.yml
rm -f "$HOME/.ssh/deploy_key"
rm -f "$HOME/.ssh/config"
rm -rf "$RUNNER_TEMP/sops-age"
rm -f "$RUNNER_TEMP/bootstrap.yml"
