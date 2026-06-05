#!/bin/bash

set -euo pipefail

SSH_TARGET="${1:-gtr}"

echo "==> Reapplying Tailscale service-host mappings on ${SSH_TARGET}"

ssh "$SSH_TARGET" 'bash -se' <<'REMOTE_EOF'
set -euo pipefail

services=(
  "svc:corp-finance-monitor|http://127.0.0.1:8190"
  "svc:grafana|http://localhost:3000"
  "svc:mihomo-api|http://127.0.0.1:9090"
  "svc:victoriametrics|http://localhost:8428"
  "svc:victorialogs|http://localhost:8429"
  "svc:envoy-admin|http://127.0.0.1:9901"
)

for entry in "${services[@]}"; do
  IFS='|' read -r service target <<<"$entry"
  echo "--> ${service} => ${target}"
  sudo tailscale serve --service="${service}" --https=443 "${target}" >/dev/null
done

echo
echo "Current service-host mappings:"
sudo tailscale serve status
REMOTE_EOF
