#!/bin/bash
# Shadowsocks + Shadow-TLS 一键部署脚本
# Usage: ./deploy.sh [server|client|verify|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$SCRIPT_DIR/ansible"
INVENTORY="$ANSIBLE_DIR/inventory.ini"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 Ansible 是否安装
check_ansible() {
    if ! command -v ansible-playbook &> /dev/null; then
        print_error "Ansible 未安装。请先安装 Ansible："
        echo "  Ubuntu/Debian: sudo apt install ansible"
        echo "  macOS: pip install ansible"
        exit 1
    fi
    print_info "Ansible 版本: $(ansible --version | head -n1)"
}

# 检查 inventory 配置
check_inventory() {
    if [[ ! -f "$INVENTORY" ]]; then
        print_error "Inventory 文件不存在: $INVENTORY"
        exit 1
    fi
    print_info "使用 Inventory: $INVENTORY"
}

# 测试 SSH 连接
test_connection() {
    local host=$1
    print_info "测试连接到 $host ..."

    if ansible -i "$INVENTORY" "$host" -m ping &> /dev/null; then
        print_info "✓ 连接到 $host 成功"
        return 0
    else
        print_error "✗ 连接到 $host 失败"
        return 1
    fi
}

# 部署服务器端
deploy_server() {
    print_info "========================================="
    print_info "部署 Shadowsocks + Shadow-TLS 服务器端"
    print_info "========================================="

    test_connection "remote_server" || exit 1

    print_info "开始部署..."
    ansible-playbook -i "$INVENTORY" "$ANSIBLE_DIR/server-deploy.yml"

    if [[ $? -eq 0 ]]; then
        print_info "✓ 服务器端部署成功"
        print_info "下一步: ./deploy.sh client"
    else
        print_error "✗ 服务器端部署失败"
        exit 1
    fi
}

# 部署客户端
deploy_client() {
    print_info "========================================="
    print_info "部署 Shadowsocks + Shadow-TLS 客户端"
    print_info "========================================="

    test_connection "client_server" || exit 1

    print_info "开始部署..."
    ansible-playbook -i "$INVENTORY" "$ANSIBLE_DIR/client-deploy.yml"

    if [[ $? -eq 0 ]]; then
        print_info "✓ 客户端部署成功"
        print_info "下一步: ./deploy.sh verify"
    else
        print_error "✗ 客户端部署失败"
        exit 1
    fi
}

# 验证部署
verify() {
    print_info "========================================="
    print_info "验证部署"
    print_info "========================================="

    test_connection "remote_server" || print_warn "无法连接到服务器"
    test_connection "client_server" || print_warn "无法连接到客户端"

    print_info "运行验证测试..."
    ansible-playbook -i "$INVENTORY" "$ANSIBLE_DIR/verify.yml"

    if [[ $? -eq 0 ]]; then
        print_info "✓ 验证完成"
        print_info "请在 GTR 服务器上手动测试："
        echo "  curl --socks5 127.0.0.1:1080 https://api.ipify.org"
    else
        print_warn "验证发现一些问题，请检查输出"
    fi
}

# 完整部署
deploy_all() {
    print_info "========================================="
    print_info "完整部署流程"
    print_info "========================================="

    # 部署服务器端
    deploy_server

    echo ""
    read -p "按 Enter 继续部署客户端..."

    # 部署客户端
    deploy_client

    echo ""
    read -p "按 Enter 继续验证..."

    # 验证
    verify
}

# 显示帮助
show_help() {
    cat << EOF
Shadowsocks + Shadow-TLS 部署脚本

Usage: $0 [COMMAND]

Commands:
    server   部署服务器端 (142.171.205.19)
    client   部署客户端 (GTR)
    verify   验证部署
    all      完整部署 (server + client + verify)
    help     显示此帮助信息

Examples:
    $0 all              # 完整部署
    $0 server           # 仅部署服务器端
    $0 client           # 仅部署客户端
    $0 verify           # 验证部署

Configuration:
    编辑 $ANSIBLE_DIR/group_vars/all/public.yml，并通过 private vault 提供 secret.runtime.yml
    编辑 $INVENTORY 配置服务器地址和用户

Requirements:
    - Ansible 2.9+
    - SSH 访问到目标服务器
    - 目标服务器上的 sudo 权限

EOF
}

# 主函数
main() {
    local command=${1:-help}

    check_ansible
    check_inventory

    case "$command" in
        server)
            deploy_server
            ;;
        client)
            deploy_client
            ;;
        verify)
            verify
            ;;
        all)
            deploy_all
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $command"
            show_help
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
