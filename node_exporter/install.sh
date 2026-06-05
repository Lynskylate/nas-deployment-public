#!/bin/bash
# Node Exporter 部署脚本
# 用于在 gtr 服务器上安装 node_exporter

set -e

# 配置变量
NODE_EXPORTER_VERSION="1.8.2"
NODE_EXPORTER_USER="node_exporter"
NODE_EXPORTER_GROUP="node_exporter"
INSTALL_DIR="/usr/local/node_exporter"
DOWNLOAD_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否为 root 或有 sudo 权限
check_privileges() {
    if [[ $EUID -eq 0 ]]; then
        # 已是 root 用户
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        # 尝试使用 sudo
        if sudo -v >/dev/null 2>&1; then
            SUDO="sudo"
        else
            log_error "此脚本需要 root 权限或 sudo 访问权限"
            log_error "请使用: sudo $0"
            exit 1
        fi
    else
        log_error "此脚本需要 root 权限，且未找到 sudo 命令"
        exit 1
    fi
}

# 检测系统架构
detect_architecture() {
    ARCH=$(uname -m)
    case $ARCH in
        x86_64)
            DOWNLOAD_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
            ;;
        aarch64)
            DOWNLOAD_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-arm64.tar.gz"
            ;;
        *)
            log_error "不支持的系统架构: $ARCH"
            exit 1
            ;;
    esac
    log_info "检测到系统架构: $ARCH"
}

# 创建用户和组
create_user() {
    log_info "创建 node_exporter 用户和组..."

    if $SUDO getent group "$NODE_EXPORTER_GROUP" >/dev/null 2>&1; then
        log_warn "组 $NODE_EXPORTER_GROUP 已存在"
    else
        $SUDO groupadd --system "$NODE_EXPORTER_GROUP"
    fi

    if $SUDO id "$NODE_EXPORTER_USER" >/dev/null 2>&1; then
        log_warn "用户 $NODE_EXPORTER_USER 已存在"
    else
        $SUDO useradd --system \
            --home-dir "$INSTALL_DIR" \
            --no-create-home \
            --shell /usr/sbin/nologin \
            --gid "$NODE_EXPORTER_GROUP" \
            "$NODE_EXPORTER_USER"
    fi
}

# 下载并安装 node_exporter
install_node_exporter() {
    log_info "下载 node_exporter v${NODE_EXPORTER_VERSION}..."

    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    if ! command -v wget >/dev/null 2>&1; then
        $SUDO apt-get update && $SUDO apt-get install -y wget
    fi

    wget -q --show-progress "$DOWNLOAD_URL" -O node_exporter.tar.gz

    log_info "解压并安装二进制文件..."

    $SUDO mkdir -p "$INSTALL_DIR"
    $SUDO tar -xzf node_exporter.tar.gz --strip-components=1 -C "$INSTALL_DIR"

    $SUDO chown -R "$NODE_EXPORTER_USER:$NODE_EXPORTER_GROUP" "$INSTALL_DIR"
    $SUDO chmod +x "$INSTALL_DIR/node_exporter"

    # 清理临时文件
    cd -
    rm -rf "$TEMP_DIR"

    log_info "node_exporter 已安装到 $INSTALL_DIR"
}

# 创建 systemd 服务
create_systemd_service() {
    log_info "创建 systemd 服务..."

    $SUDO tee /etc/systemd/system/node_exporter.service >/dev/null <<EOF
[Unit]
Description=Prometheus Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$NODE_EXPORTER_USER
Group=$NODE_EXPORTER_GROUP

ExecStart=$INSTALL_DIR/node_exporter \\
    --web.listen-address=:9100 \\
    --path.procfs=/proc \\
    --path.sysfs=/sys \\
    --path.rootfs=/ \\
    --collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/proc /sys

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload
    log_info "systemd 服务已创建"
}

# 配置防火墙（如果启用）
configure_firewall() {
    if command -v ufw >/dev/null 2>&1 && $SUDO ufw status | grep -q "Status: active"; then
        log_info "配置防火墙规则..."
        $SUDO ufw allow 9100/tcp comment "Node Exporter"
    fi
}

# 启动服务
start_service() {
    log_info "启动 node_exporter 服务..."

    $SUDO systemctl enable node_exporter
    $SUDO systemctl start node_exporter

    # 等待服务启动
    sleep 2

    if $SUDO systemctl is-active --quiet node_exporter; then
        log_info "✓ node_exporter 服务已成功启动"
    else
        log_error "✗ node_exporter 服务启动失败"
        $SUDO journalctl -u node_exporter -n 20 --no-pager
        exit 1
    fi
}

# 验证安装
verify_installation() {
    log_info "验证安装..."

    # 检查端口
    if $SUDO ss -tulnp | grep -q ":9100"; then
        log_info "✓ 端口 9100 正在监听"
    else
        log_warn "端口 9100 未监听，请检查服务状态"
    fi

    # 测试 metrics 端点
    if command -v curl >/dev/null 2>&1; then
        if curl -s http://localhost:9100/metrics | grep -q "node_"; then
            log_info "✓ Metrics 端点响应正常"
        else
            log_warn "Metrics 端点响应异常"
        fi
    fi

    # 显示版本
    VERSION=$($INSTALL_DIR/node_exporter --version 2>&1 | head -1)
    log_info "已安装版本: $VERSION"
}

# 显示后续步骤
show_next_steps() {
    echo ""
    log_info "========================================"
    log_info "Node Exporter 安装完成！"
    log_info "========================================"
    echo ""
    echo "常用命令："
    echo "  查看服务状态:  sudo systemctl status node_exporter"
    echo "  查看日志:      sudo journalctl -u node_exporter -f"
    echo "  重启服务:      sudo systemctl restart node_exporter"
    echo "  停止服务:      sudo systemctl stop node_exporter"
    echo ""
    echo "访问端点："
    echo "  Metrics:        http://$(hostname -I | awk '{print $1}'):9100/metrics"
    echo ""
}

# 主流程
main() {
    log_info "开始安装 Node Exporter v${NODE_EXPORTER_VERSION}..."
    echo ""

    check_privileges
    detect_architecture
    create_user
    install_node_exporter
    create_systemd_service
    configure_firewall
    start_service
    verify_installation
    show_next_steps
}

# 执行主流程
main
