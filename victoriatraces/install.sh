#!/bin/bash
# VictoriaTraces 部署脚本
# 用于在 gtr 服务器上安装 VictoriaTraces

set -e

VICTORIATRACES_VERSION="0.7.1"
VICTORIATRACES_USER="victoriatraces"
VICTORIATRACES_GROUP="victoriatraces"
INSTALL_DIR="/usr/local/victoriatraces"
DATA_DIR="/var/lib/victoriatraces/data"
HTTP_PORT="9428"
DOWNLOAD_URL="https://github.com/VictoriaMetrics/VictoriaTraces/releases/download/v${VICTORIATRACES_VERSION}/victoria-traces-linux-amd64-v${VICTORIATRACES_VERSION}.tar.gz"

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

check_privileges() {
    if [[ $EUID -eq 0 ]]; then
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        if sudo -v >/dev/null 2>&1; then
            SUDO="sudo"
        else
            log_error "此脚本需要 root 权限或 sudo 访问权限"
            exit 1
        fi
    else
        log_error "此脚本需要 root 权限"
        exit 1
    fi
}

detect_architecture() {
    ARCH=$(uname -m)
    case $ARCH in
        x86_64)
            DOWNLOAD_URL="https://github.com/VictoriaMetrics/VictoriaTraces/releases/download/v${VICTORIATRACES_VERSION}/victoria-traces-linux-amd64-v${VICTORIATRACES_VERSION}.tar.gz"
            ;;
        aarch64)
            DOWNLOAD_URL="https://github.com/VictoriaMetrics/VictoriaTraces/releases/download/v${VICTORIATRACES_VERSION}/victoria-traces-linux-arm64-v${VICTORIATRACES_VERSION}.tar.gz"
            ;;
        *)
            log_error "不支持的系统架构: $ARCH"
            exit 1
            ;;
    esac
    log_info "检测到系统架构: $ARCH"
}

create_user() {
    log_info "创建 victoriatraces 用户和组..."

    if $SUDO getent group "$VICTORIATRACES_GROUP" >/dev/null 2>&1; then
        log_warn "组 $VICTORIATRACES_GROUP 已存在"
    else
        $SUDO groupadd --system "$VICTORIATRACES_GROUP"
    fi

    if $SUDO id "$VICTORIATRACES_USER" >/dev/null 2>&1; then
        log_warn "用户 $VICTORIATRACES_USER 已存在"
    else
        $SUDO useradd --system \
            --home-dir "$INSTALL_DIR" \
            --no-create-home \
            --shell /usr/sbin/nologin \
            --gid "$VICTORIATRACES_GROUP" \
            "$VICTORIATRACES_USER"
    fi
}

install_victoriatraces() {
    log_info "下载 VictoriaTraces v${VICTORIATRACES_VERSION}..."

    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    if ! command -v wget >/dev/null 2>&1; then
        $SUDO apt-get update && $SUDO apt-get install -y wget
    fi

    wget -q --show-progress "$DOWNLOAD_URL" -O victoria-traces.tar.gz

    log_info "解压并安装二进制文件..."

    $SUDO mkdir -p "$INSTALL_DIR"
    $SUDO tar -xzf victoria-traces.tar.gz --strip-components=1 -C "$INSTALL_DIR"

    $SUDO chown -R "$VICTORIATRACES_USER:$VICTORIATRACES_GROUP" "$INSTALL_DIR"
    $SUDO chmod +x "$INSTALL_DIR/victoria-traces-prod"

    $SUDO mkdir -p "$DATA_DIR"
    $SUDO chown -R "$VICTORIATRACES_USER:$VICTORIATRACES_GROUP" "$DATA_DIR"

    cd -
    rm -rf "$TEMP_DIR"

    log_info "VictoriaTraces 已安装到 $INSTALL_DIR"
}

create_systemd_service() {
    log_info "创建 systemd 服务..."

    $SUDO tee /etc/systemd/system/victoriatraces.service >/dev/null <<EOF
[Unit]
Description=VictoriaTraces - Distributed Tracing Storage
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$VICTORIATRACES_USER
Group=$VICTORIATRACES_GROUP

ExecStart=$INSTALL_DIR/victoria-traces-prod \\
    -storageDataPath=$DATA_DIR \\
    -httpListenAddr=:$HTTP_PORT

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload
    log_info "systemd 服务已创建"
}

configure_firewall() {
    if command -v ufw >/dev/null 2>&1 && $SUDO ufw status | grep -q "Status: active"; then
        log_info "配置防火墙规则..."
        $SUDO ufw allow ${HTTP_PORT}/tcp comment "VictoriaTraces HTTP"
    fi
}

start_service() {
    log_info "启动 victoriatraces 服务..."

    $SUDO systemctl enable victoriatraces
    $SUDO systemctl start victoriatraces

    sleep 2

    if $SUDO systemctl is-active --quiet victoriatraces; then
        log_info "victoriatraces 服务已成功启动"
    else
        log_error "victoriatraces 服务启动失败"
        $SUDO journalctl -u victoriatraces -n 20 --no-pager
        exit 1
    fi
}

verify_installation() {
    log_info "验证安装..."

    if $SUDO ss -tulnp | grep -q ":${HTTP_PORT}"; then
        log_info "端口 ${HTTP_PORT} 正在监听"
    else
        log_warn "端口 ${HTTP_PORT} 未监听"
    fi

    if command -v curl >/dev/null 2>&1; then
        sleep 1
        if curl -s http://localhost:${HTTP_PORT}/health | grep -q "OK"; then
            log_info "Health 端点响应正常"
        else
            log_warn "Health 端点响应异常"
        fi
    fi
}

show_next_steps() {
    echo ""
    log_info "========================================"
    log_info "VictoriaTraces 安装完成！"
    log_info "========================================"
    echo ""
    echo "常用命令："
    echo "  查看服务状态:  sudo systemctl status victoriatraces"
    echo "  查看日志:      sudo journalctl -u victoriatraces -f"
    echo "  重启服务:      sudo systemctl restart victoriatraces"
    echo ""
    echo "访问端点："
    echo "  VMUI:          http://$(hostname -I | awk '{print $1}'):${HTTP_PORT}/vmui"
    echo "  Health:        http://$(hostname -I | awk '{print $1}'):${HTTP_PORT}/health"
    echo "  Metrics:       http://$(hostname -I | awk '{print $1}'):${HTTP_PORT}/metrics"
    echo ""
    echo "数据摄入端点："
    echo "  OTLP/HTTP:     http://$(hostname -I | awk '{print $1}'):${HTTP_PORT}/insert/opentelemetry/v1/traces"
    echo ""
    echo "Grafana 集成："
    echo "  添加 Jaeger 数据源，URL: http://$(hostname -I | awk '{print $1}'):${HTTP_PORT}/select/jaeger"
    echo ""
}

main() {
    log_info "开始安装 VictoriaTraces v${VICTORIATRACES_VERSION}..."
    echo ""

    check_privileges
    detect_architecture
    create_user
    install_victoriatraces
    create_systemd_service
    configure_firewall
    start_service
    verify_installation
    show_next_steps
}

main
