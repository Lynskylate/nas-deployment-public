#!/bin/bash
# 兼容旧入口，统一走当前 deploy-alerts.sh。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/deploy-alerts.sh"
