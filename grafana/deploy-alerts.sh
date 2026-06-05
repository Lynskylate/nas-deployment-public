#!/bin/bash
# Grafana 告警配置部署脚本
# 当前脚本要求 alert-rules.yaml 来自当前 Grafana 版本的导出结果。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RULES_SOURCE="$SCRIPT_DIR/alert-rules.yaml"
RULES_TARGET="/usr/local/grafana/conf/provisioning/alerting/rules.yaml"

echo "=== 开始部署 Grafana 告警配置 ==="

if [ ! -f "$RULES_SOURCE" ]; then
    echo "✗ 未找到规则文件: $RULES_SOURCE" >&2
    exit 1
fi

if grep -n '\\$labels\|\\$value' "$RULES_SOURCE" >/dev/null; then
    echo "✗ 检测到被转义的 Grafana 模板变量（例如 \\$labels / \\$value）" >&2
    echo "  请先修正 alert-rules.yaml，再重新部署。" >&2
    exit 1
fi

if ! grep -q 'relativeTimeRange:' "$RULES_SOURCE"; then
    echo "✗ $RULES_SOURCE 缺少 relativeTimeRange，和当前 Grafana 告警 provisioning 格式不兼容。" >&2
    echo "  请先从 Grafana UI 或 provisioning API 导出当前版本的规则 YAML，再重新部署。" >&2
    exit 1
fi

echo "1. 部署告警规则文件..."
sudo install -o root -g root -m 0644 "$RULES_SOURCE" "$RULES_TARGET"
echo "✓ 告警规则文件已部署"

echo "2. 重启 Grafana 服务..."
sudo systemctl restart grafana
echo "✓ Grafana 服务已重启"

echo "3. 检查 Grafana 服务状态..."
if systemctl is-active --quiet grafana; then
    echo "✓ Grafana 服务运行正常"
    echo "=== 部署完成 ==="
else
    echo "✗ Grafana 服务启动失败" >&2
    echo "查看日志: journalctl -u grafana -n 50" >&2
    exit 1
fi
