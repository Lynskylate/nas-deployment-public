#!/usr/bin/env bash
# validate-contract.sh — 交叉验证两层资源 manifest 是否有冲突
# 用法:
#   validate-contract.sh <infra-manifest> <app-manifest>
#   validate-contract.sh --ssh <host> <app-manifest>    # SSH 读取远端 infra manifest
#
# 退出码:
#   0 = 无冲突
#   1 = 发现冲突
#   2 = 参数错误

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

conflicts=()

usage() {
  echo "Usage: $0 <infra-manifest.yml> <app-manifest.yml>"
  echo "       $0 --ssh <user@host> <app-manifest.yml>"
  exit 2
}

# 读取 infra manifest
if [[ "${1:-}" == "--ssh" ]]; then
  [[ $# -lt 3 ]] && usage
  SSH_HOST="$2"
  APP_MANIFEST="$3"
  INFRA_MANIFEST=$(mktemp)
  trap "rm -f $INFRA_MANIFEST" EXIT
  echo "Fetching infrastructure manifest from $SSH_HOST..."
  ssh "$SSH_HOST" "cat /etc/gtr/resource-manifest.infra.yml" > "$INFRA_MANIFEST" 2>/dev/null || {
    echo -e "${YELLOW}WARNING: Infrastructure manifest not found on $SSH_HOST${NC}"
    echo "  First infrastructure deploy may not have run yet."
    echo "  Skipping contract validation."
    exit 0
  }
else
  [[ $# -lt 2 ]] && usage
  INFRA_MANIFEST="$1"
  APP_MANIFEST="$2"
fi

[[ -f "$INFRA_MANIFEST" ]] || { echo "ERROR: Infrastructure manifest not found: $INFRA_MANIFEST" >&2; exit 2; }
[[ -f "$APP_MANIFEST" ]]   || { echo "ERROR: Application manifest not found: $APP_MANIFEST" >&2; exit 2; }

echo "Validating resource contract..."
echo "  Infrastructure: $INFRA_MANIFEST"
echo "  Application:    $APP_MANIFEST"
echo ""

# 验证逻辑用 Python (PyYAML)
python3 - "$INFRA_MANIFEST" "$APP_MANIFEST" <<'PYEOF'
import yaml
import sys

def load_manifest(path):
    with open(path) as f:
        return yaml.safe_load(f)

def check_subuid_overlap(infra, app):
    """检查 subuid 范围是否有交集"""
    conflicts = []
    infra_ranges = infra.get('subuid', []) or []
    app_ranges = app.get('subuid', []) or []

    for a in app_ranges:
        a_start = a['start']
        a_end = a_start + a['size']
        for i in infra_ranges:
            i_start = i['start']
            i_end = i_start + i['size']
            # 检查范围重叠
            if a_start < i_end and i_start < a_end:
                conflicts.append(
                    f"subuid OVERLAP: {a['user']} [{a_start}-{a_end}) "
                    f"conflicts with {i['user']} [{i_start}-{i_end})"
                )
    return conflicts

def check_port_conflicts(infra, app):
    """检查端口声明是否冲突"""
    conflicts = []
    infra_ports = {(p['port'], p.get('protocol', 'tcp')) for p in (infra.get('ports', []) or [])}
    app_ports = {(p['port'], p.get('protocol', 'tcp')): p for p in (app.get('ports', []) or [])}

    for (port, proto), p_info in app_ports.items():
        if (port, proto) in infra_ports:
            conflicts.append(
                f"port CONFLICT: {proto}/{port} ({p_info.get('service', '?')}) "
                f"is claimed by both layers"
            )
    return conflicts

def check_user_conflicts(infra, app):
    """检查用户名是否冲突"""
    conflicts = []
    infra_users = {u['user'] for u in (infra.get('users', []) or [])}
    app_users = {u['user'] for u in (app.get('users', []) or [])}

    overlap = infra_users & app_users
    for user in overlap:
        conflicts.append(f"user CONFLICT: '{user}' is declared in both layers")
    return conflicts

def check_nftables(infra, app):
    """应用层不应声明 nftables chains"""
    conflicts = []
    app_chains = app.get('nftables_chains', []) or []
    if app_chains:
        conflicts.append(
            f"nftables VIOLATION: application layer declares chains {app_chains} "
            f"(reserved for infrastructure only)"
        )
    return conflicts

def main():
    infra = load_manifest(sys.argv[1])
    app = load_manifest(sys.argv[2])

    all_conflicts = []
    all_conflicts.extend(check_subuid_overlap(infra, app))
    all_conflicts.extend(check_port_conflicts(infra, app))
    all_conflicts.extend(check_user_conflicts(infra, app))
    all_conflicts.extend(check_nftables(infra, app))

    if all_conflicts:
        print("CONTRACT VALIDATION FAILED")
        print(f"  Found {len(all_conflicts)} conflict(s):\n")
        for c in all_conflicts:
            print(f"  ✗ {c}")
        sys.exit(1)
    else:
        # 统计
        infra_ports = len(infra.get('ports', []) or [])
        app_ports = len(app.get('ports', []) or [])
        infra_subuid = len(infra.get('subuid', []) or [])
        app_subuid = len(app.get('subuid', []) or [])
        print("CONTRACT VALIDATION PASSED")
        print(f"  Ports:  {infra_ports} infra + {app_ports} app (no overlap)")
        print(f"  Subuid: {infra_subuid} infra + {app_subuid} app (no overlap)")
        sys.exit(0)

if __name__ == '__main__':
    main()
PYEOF

exit_code=$?
if [[ $exit_code -eq 0 ]]; then
  echo -e "\n${GREEN}✓ Resource contract is valid${NC}"
else
  echo -e "\n${RED}✗ Resource contract violated — fix conflicts before deploying${NC}"
fi
exit $exit_code
