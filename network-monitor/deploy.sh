#!/bin/bash
#
# Network Monitoring Deployment Script
# Deploys network connectivity monitoring to gtr server
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print colored message
print_msg() {
    local color=$1
    shift
    echo -e "${color}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"
}

# Check if ansible is installed
check_ansible() {
    if ! command -v ansible-playbook &> /dev/null; then
        print_msg "$RED" "Error: ansible-playbook is not installed"
        print_msg "$YELLOW" "Install with: sudo apt install ansible"
        exit 1
    fi
}

# Test network monitoring locally
test_local() {
    print_msg "$YELLOW" "Testing network monitoring script locally..."

    # Create temp log directory
    TEMP_LOG=$(mktemp -d)
    export LOG_FILE="$TEMP_LOG/test.log"

    # Run the script
    bash "$SCRIPT_DIR/network-monitor.sh" all

    echo ""
    print_msg "$GREEN" "Local test completed. Sample output:"
    cat "$LOG_FILE" 2>/dev/null || bash "$SCRIPT_DIR/network-monitor.sh" all

    # Cleanup
    rm -rf "$TEMP_LOG"
}

# Deploy to remote server
deploy() {
    local action="${1:-deploy}"

    check_ansible

    case "$action" in
        deploy)
            print_msg "$YELLOW" "Deploying network monitoring to gtr server..."
            ansible-playbook -i ansible/inventory.ini ansible/deploy.yml
            print_msg "$GREEN" "Deployment completed successfully!"
            print_msg "$YELLOW" "Check logs with: ssh gtr 'tail -f /var/log/network-monitor/network-monitor.log'"
            ;;
        verify)
            print_msg "$YELLOW" "Verifying deployment on gtr server..."
            ansible monitoring_servers -i ansible/inventory.ini -m shell -a "
                echo '=== Script Location ===' && ls -la /usr/local/network-monitor/ && \
                echo '' && echo '=== Log File ===' && ls -la /var/log/network-monitor/ && \
                echo '' && echo '=== Cron Job ===' && crontab -l | grep network-monitor && \
                echo '' && echo '=== Vector Status ===' && systemctl status vector --no-pager -l | head -10 && \
                echo '' && echo '=== Latest Log Entries ===' && tail -5 /var/log/network-monitor/network-monitor.log
            "
            ;;
        test)
            print_msg "$YELLOW" "Running manual test on gtr server..."
            ansible monitoring_servers -i ansible/inventory.ini -m shell -a "
                /usr/local/network-monitor/network-monitor.sh all
            "
            ;;
        logs)
            print_msg "$YELLOW" "Fetching network monitor logs from gtr server..."
            ansible monitoring_servers -i ansible/inventory.ini -m shell -a "
                tail -20 /var/log/network-monitor/network-monitor.log
            "
            ;;
        uninstall)
            print_msg "$YELLOW" "Uninstalling network monitoring from gtr server..."
            ansible monitoring_servers -i ansible/inventory.ini -m shell -a "
                crontab -l | grep -v 'network-monitor' | crontab - && \
                rm -rf /usr/local/network-monitor && \
                rm -f /etc/logrotate.d/network-monitor
            "
            print_msg "$GREEN" "Uninstall completed. Note: Vector config was backed up."
            ;;
        *)
            echo "Usage: $0 {deploy|verify|test|logs|uninstall}"
            echo ""
            echo "Commands:"
            echo "  deploy    - Deploy network monitoring to gtr server (default)"
            echo "  verify    - Verify deployment status"
            echo "  test      - Run manual test on gtr server"
            echo "  logs      - Show recent logs from gtr server"
            echo "  uninstall - Remove network monitoring from gtr server"
            echo "  local     - Test script locally"
            exit 1
            ;;
    esac
}

# Main
case "${1:-deploy}" in
    local)
        test_local
        ;;
    deploy|verify|test|logs|uninstall)
        deploy "$1"
        ;;
    *)
        echo "Usage: $0 {deploy|verify|test|logs|uninstall|local}"
        echo ""
        echo "Commands:"
        echo "  deploy    - Deploy network monitoring to gtr server (default)"
        echo "  verify    - Verify deployment status"
        echo "  test      - Run manual test on gtr server"
        echo "  logs      - Show recent logs from gtr server"
        echo "  uninstall - Remove network monitoring from gtr server"
        echo "  local     - Test script locally"
        exit 1
        ;;
esac
