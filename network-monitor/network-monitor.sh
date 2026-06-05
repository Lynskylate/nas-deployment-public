#!/bin/bash
#
# Network Connectivity Monitoring Script via Mihomo Proxy
# Tests multiple endpoints to verify Mihomo routing rules are working correctly
#
# Domestic sites should be fast (direct routing by Mihomo)
# International sites should work (routed through upstream proxy)
#

# Configuration
LOG_FILE="/var/log/network-monitor/network-monitor.log"
PROXY_HOST="127.0.0.1"
PROXY_PORT="7890"
PROXY="${PROXY_HOST}:${PROXY_PORT}"
TIMEOUT_SECONDS=10

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Get current timestamp in ISO 8601 format
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Test a single URL through Mihomo proxy
# $1: site_name - Identifier for the site
# $2: url - Full URL to test
# $3: expected_route - Expected routing: "direct" (domestic) or "proxy" (international)
# $4: category - Service category (streaming, cdn, api, etc.)
test_site() {
    local site_name="$1"
    local url="$2"
    local expected_route="$3"
    local category="${4:-general}"

    # Build curl command with Mihomo proxy
    local curl_cmd="curl -o /dev/null -s -w \"%{http_code} %{time_total}\" --max-time ${TIMEOUT_SECONDS} -x ${PROXY} \"${url}\""

    # Execute curl and capture result
    response=$(eval "$curl_cmd" 2>&1)
    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        # Parse response
        status_code=$(echo "$response" | cut -d' ' -f1)
        response_time=$(echo "$response" | cut -d' ' -f2)

        # Validate response time is a number
        if ! [[ "$response_time" =~ ^[0-9]+\.?[0-9]*$ ]]; then
            response_time=0
        fi
    else
        # Connection failed
        status_code="000"
        response_time=0
    fi

    # Output JSON log entry with category
    echo "{\"timestamp\":\"${TIMESTAMP}\",\"site\":\"${site_name}\",\"url\":\"${url}\",\"status_code\":${status_code},\"response_time\":${response_time},\"proxy\":\"mihomo\",\"expected_route\":\"${expected_route}\",\"category\":\"${category}\"}"
}

# Main execution
case "${1:-all}" in
    all)
        # === Domestic Sites (should be routed directly by Mihomo - fast) ===
        # CDN 测速点
        test_site "xiaomi-204" "http://connect.rom.miui.com/generate_204" "direct" "cdn"
        test_site "miui-cdn" "http://www.miui.com" "direct" "cdn"

        # 搜索引擎
        test_site "baidu" "http://www.baidu.com" "direct" "search"
        test_site "bing-cn" "http://cn.bing.com" "direct" "search"

        # 电商
        test_site "taobao" "https://www.taobao.com" "direct" "ecommerce"
        test_site "jd" "https://www.jd.com" "direct" "ecommerce"
        test_site "alipay" "https://www.alipay.com" "direct" "payment"

        # 社交/视频
        test_site "bilibili" "https://www.bilibili.com" "direct" "video"
        test_site "qq" "https://im.qq.com" "direct" "social"

        # === International Sites (should be routed through upstream by Mihomo) ===
        # Google 服务
        test_site "google-204" "http://www.google.com/generate_204" "proxy" "cdn"
        test_site "google-search" "https://www.google.com" "proxy" "search"
        test_site "gstatic" "http://www.gstatic.com/generate_204" "proxy" "cdn"

        # 流媒体
        test_site "youtube-204" "https://www.youtube.com/generate_204" "proxy" "streaming"
        test_site "netflix" "https://www.netflix.com" "proxy" "streaming"

        # GitHub/开发工具
        test_site "github-api" "https://api.github.com" "proxy" "api"
        test_site "github-raw" "https://raw.githubusercontent.com" "proxy" "cdn"
        test_site "github-assets" "https://githubassets.com" "proxy" "cdn"
        test_site "github-avatars" "https://avatars.githubusercontent.com" "proxy" "cdn"
        test_site "stackoverflow" "https://stackoverflow.com" "proxy" "dev"

        # Cloudflare
        test_site "cloudflare" "http://www.cloudflare.com/cdn-cgi/trace" "proxy" "cdn"
        test_site "cloudflare-cdn" "https://cp.cloudflare.com" "proxy" "cdn"

        # OpenAI
        test_site "openai" "https://api.openai.com" "proxy" "ai"
        test_site "chatgpt" "https://chatgpt.com" "proxy" "ai"

        # 社交媒体
        test_site "twitter" "https://x.com" "proxy" "social"
        test_site "telegram-web" "https://web.telegram.org" "proxy" "social"

        # 新闻/资讯
        test_site "reddit" "https://www.reddit.com" "proxy" "social"
        ;;
    domestic)
        # Test only domestic sites
        test_site "xiaomi-204" "http://connect.rom.miui.com/generate_204" "direct" "cdn"
        test_site "baidu" "http://www.baidu.com" "direct" "search"
        test_site "taobao" "https://www.taobao.com" "direct" "ecommerce"
        test_site "alipay" "https://www.alipay.com" "direct" "payment"
        test_site "bilibili" "https://www.bilibili.com" "direct" "video"
        ;;
    international)
        # Test only international sites
        test_site "google-204" "http://www.google.com/generate_204" "proxy" "cdn"
        test_site "youtube-204" "https://www.youtube.com/generate_204" "proxy" "streaming"
        test_site "github-api" "https://api.github.com" "proxy" "api"
        test_site "github-assets" "https://githubassets.com" "proxy" "cdn"
        test_site "cloudflare" "http://www.cloudflare.com/cdn-cgi/trace" "proxy" "cdn"
        test_site "openai" "https://api.openai.com" "proxy" "ai"
        ;;
    github)
        # Test GitHub ecosystem only
        test_site "github-api" "https://api.github.com" "proxy" "api"
        test_site "github-raw" "https://raw.githubusercontent.com" "proxy" "cdn"
        test_site "github-assets" "https://githubassets.com" "proxy" "cdn"
        test_site "github-avatars" "https://avatars.githubusercontent.com" "proxy" "cdn"
        ;;
    streaming)
        # Test streaming services
        test_site "youtube-204" "https://www.youtube.com/generate_204" "proxy" "streaming"
        test_site "netflix" "https://www.netflix.com" "proxy" "streaming"
        test_site "bilibili" "https://www.bilibili.com" "direct" "video"
        ;;
    *)
        echo "Usage: $0 [all|domestic|international|github|streaming]"
        echo ""
        echo "Commands:"
        echo "  all           - Test all sites through Mihomo proxy (default)"
        echo "  domestic      - Test domestic sites only"
        echo "  international - Test international sites only"
        echo "  github        - Test GitHub ecosystem only"
        echo "  streaming     - Test streaming services only"
        echo ""
        echo "All tests go through Mihomo proxy to verify routing rules:"
        echo "  - Domestic sites should be fast (direct routing)"
        echo "  - International sites should work (upstream routing)"
        exit 1
        ;;
esac
