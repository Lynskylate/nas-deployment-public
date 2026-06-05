#!/bin/bash
#
# Network Monitoring Wrapper Script
# This script runs the network monitor and appends results to log file
# Designed to be called by cron
#

LOG_FILE="/var/log/network-monitor/network-monitor.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Run network monitor for all sites and append to log file
"$SCRIPT_DIR/network-monitor.sh" all >> "$LOG_FILE" 2>&1
