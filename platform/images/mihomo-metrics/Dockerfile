# mihomo-metrics collector image
# Pre-installs curl + jq + bash to eliminate runtime apk add dependency
FROM alpine:3.19

RUN apk add --no-cache curl jq bash

# Script is mounted via ConfigMap at /scripts/mihomo-metrics.sh
# The Deployment command: exec /scripts/mihomo-metrics.sh

ENTRYPOINT ["/bin/bash", "/scripts/mihomo-metrics.sh"]
