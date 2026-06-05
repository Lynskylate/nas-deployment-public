#!/bin/bash
#
# Mihomo Monitoring Integration - One-Click Installer
# Deploys metrics collector and log forwarding to VictoriaMetrics/VictoriaLogs
#
# Usage:
#   ./install.sh           # Deploy to gtr server
#   ./install.sh verify    # Verify deployment
#   ./install.sh clean     # Remove monitoring integration
#

set -euo pipefail

# Configuration
ANSIBLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/ansible" && pwd)"
INVENTORY="${ANSIBLE_DIR}/inventory.ini"
PLAYBOOK="${ANSIBLE_DIR}/deploy.yml"
TARGET_HOST="${TARGET_HOST:-192.168.31.59}"  # gtr server
SSH_USER="${SSH_USER:-root}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Pre-flight checks
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if ansible is installed
    if ! command -v ansible-playbook &> /dev/null; then
        log_error "ansible-playbook not found. Please install ansible:"
        echo "  sudo apt install ansible"
        exit 1
    fi

    # Check if inventory file exists
    if [ ! -f "$INVENTORY" ]; then
        log_error "Inventory file not found: $INVENTORY"
        exit 1
    fi

    # Check if playbook exists
    if [ ! -f "$PLAYBOOK" ]; then
        log_error "Playbook file not found: $PLAYBOOK"
        exit 1
    fi

    # Test SSH connectivity
    log_info "Testing SSH connectivity to $SSH_USER@$TARGET_HOST..."
    if ! ssh -o ConnectTimeout=5 "$SSH_USER@$TARGET_HOST" "echo 'SSH connection successful'" 2>/dev/null; then
        log_error "Cannot connect to $SSH_USER@$TARGET_HOST via SSH"
        exit 1
    fi

    log_info "Prerequisites check passed ✓"
}

# Deploy monitoring integration
deploy() {
    log_info "Deploying mihomo monitoring integration..."

    cd "$ANSIBLE_DIR"

    ansible-playbook -i inventory.ini deploy.yml \
        -e "ansible_user=$SSH_USER" \
        --vault-password-file /dev/null \
        -v

    if [ $? -eq 0 ]; then
        log_info "Deployment completed successfully ✓"
        log_info "Run './install.sh verify' to verify the installation"
    else
        log_error "Deployment failed"
        exit 1
    fi
}

# Verify deployment
verify() {
    log_info "Verifying mihomo monitoring integration..."

    # Run the verification script on the server
    ssh "$SSH_USER@$TARGET_HOST" "sudo /usr/local/bin/mihomo-monitoring-check.sh"

    echo
    log_info "Manual verification URLs:"
    echo "  - VictoriaMetrics: http://$TARGET_HOST:8428"
    echo "  - VictoriaLogs: http://$TARGET_HOST:8429"
    echo "  - Grafana: http://$TARGET_HOST:3000"
    echo
    log_info "Query examples:"
    echo "  curl 'http://$TARGET_HOST:8428/api/v1/query?query=mihomo_scrape_success' | jq ."
    echo "  curl -G 'http://$TARGET_HOST:8429/select/log/sql/query' --data-urlencode 'query={service=\"mihomo\"}' | jq ."
}

# Clean/remove monitoring integration
clean() {
    log_warn "This will remove mihomo monitoring integration from $TARGET_HOST"
    read -p "Are you sure? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Aborted"
        exit 0
    fi

    log_info "Removing mihomo monitoring integration..."

    ssh "$SSH_USER@$TARGET_HOST" << 'EOF'
set -e

# Stop and disable services
systemctl stop mihomo-metrics.timer 2>/dev/null || true
systemctl disable mihomo-metrics.timer 2>/dev/null || true
systemctl stop mihomo-metrics.service 2>/dev/null || true
systemctl stop mihomo-logs-collector.service 2>/dev/null || true
systemctl disable mihomo-logs-collector.service 2>/dev/null || true

# Remove systemd files
rm -f /etc/systemd/system/mihomo-metrics.service
rm -f /etc/systemd/system/mihomo-metrics.timer
rm -f /etc/systemd/system/mihomo-logs-collector.service

# Remove collector scripts
rm -f /usr/local/bin/mihomo-metrics.sh
rm -f /usr/local/bin/mihomo-logs-collector.py

# Remove Vector config
rm -f /etc/vector/mihomo.yaml

# Restore Vector service
sed -i 's/ --config \/etc\/vector\/mihomo.yaml//' /etc/systemd/system/vector.service
systemctl daemon-reload
systemctl restart vector 2>/dev/null || true

# Remove verification script
rm -f /usr/local/bin/mihomo-monitoring-check.sh

echo "Cleanup completed"
EOF

    log_info "Cleanup completed ✓"
}

# Main
case "${1:-deploy}" in
    deploy)
        check_prerequisites
        deploy
        ;;
    verify)
        verify
        ;;
    clean)
        clean
        ;;
    *)
        echo "Usage: $0 {deploy|verify|clean}"
        echo ""
        echo "Commands:"
        echo "  deploy  - Deploy monitoring integration to server"
        echo "  verify  - Verify monitoring integration is working"
        echo "  clean   - Remove monitoring integration from server"
        echo ""
        echo "Environment variables:"
        echo "  TARGET_HOST - Target server (default: 192.168.31.59)"
        echo "  SSH_USER    - SSH user (default: root)"
        exit 1
        ;;
esac
