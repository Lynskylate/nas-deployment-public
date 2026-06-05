# Aliyun ECS Telemetry Configuration

本文档记录阿里云 ECS 上的 Envoy 日志和追踪配置。

## 架构概览

```
阿里云 ECS (公网)
├── Envoy
│   ├── Access Log (JSON) → /var/log/envoy/access.log
│   └── Tracing (OTLP gRPC) ──────────────┐
└── Vector                                 │
    └── 读取 access.log                    │
        ↓                                  ↓
    VictoriaLogs                      VictoriaTraces
    (gtr.tail414c32.ts.net:8429)      (gtr.tail414c32.ts.net:9429)
                ↑                                 ↑
                 ───────── Tailscale 网络 ─────────
```

## Tailscale 组网

### 安装配置

**在 GTR 和 Aliyun 上都执行：**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

### 安全配置

在 [Tailscale Admin Console](https://login.tailscale.com/admin/acls) 配置 ACL：

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["tag:aliyun-envoy"],
      "dst": ["tag:gtr-monitoring:8429", "tag:gtr-monitoring:9429"]
    }
  ],
  "tagOwners": {
    "tag:aliyun-envoy": ["autogroup:admin"],
    "tag:gtr-monitoring": ["autogroup:admin"]
  }
}
```

给设备打 tag：
```bash
# 在 Aliyun 上
sudo tailscale up --advertise-tags=tag:aliyun-envoy
```

## Envoy Access Log 配置

### 配置文件

位置: `mihomo/envoy/envoy-aliyun.yaml.j2`

```yaml
access_log:
- name: envoy.access_loggers.file
  typed_config:
    "@type": type.googleapis.com/envoy.extensions.access_loggers.file.v3.FileAccessLog
    path: /var/log/envoy/access.log
    log_format:
      json_format:
        timestamp: "%START_TIME%"
        method: "%REQ(:METHOD)%"
        path: "%REQ(X-ENVOY-ORIGINAL-PATH?:PATH)%"
        protocol: "%PROTOCOL%"
        response_code: "%RESPONSE_CODE%"
        response_flags: "%RESPONSE_FLAGS%"
        bytes_received: "%BYTES_RECEIVED%"
        bytes_sent: "%BYTES_SENT%"
        duration_ms: "%DURATION%"
        x_forwarded_for: "%REQ(X-FORWARDED-FOR)%"
        user_agent: "%REQ(USER-AGENT)%"
        request_id: "%REQ(X-REQUEST-ID)%"
        trace_id: "%TRACE_ID%"
        upstream_host: "%UPSTREAM_HOST%"
        upstream_cluster: "%UPSTREAM_CLUSTER%"
        downstream_remote_address: "%DOWNSTREAM_REMOTE_ADDRESS%"
        route_name: "%ROUTE_NAME%"
        host: "{{ ansible_hostname }}"
        service: "envoy"
```

### 日志目录权限

```bash
sudo mkdir -p /var/log/envoy
sudo chown envoy:envoy /var/log/envoy
```

## Envoy Tracing 配置

### OTLP Tracer

```yaml
tracing:
  http:
    name: envoy.tracers.opentelemetry
    typed_config:
      "@type": type.googleapis.com/envoy.config.trace.v3.OpenTelemetryConfig
      grpc_service:
        envoy_grpc:
          cluster_name: victoriatrace
      service_name: "envoy-{{ ansible_hostname }}"
```

### VictoriaTrace Cluster

```yaml
clusters:
- name: victoriatrace
  type: STRICT_DNS
  dns_lookup_family: V4_ONLY
  lb_policy: ROUND_ROBIN
  connect_timeout: 5s
  http2_protocol_options: {}
  load_assignment:
    cluster_name: victoriatrace
    endpoints:
    - lb_endpoints:
      - endpoint:
          address:
            socket_address:
              address: gtr.tail414c32.ts.net
              port_value: 9429
```

## Vector 配置

### 安装

```bash
# 通过 Ansible 自动下载到本地，然后 scp 到 ECS
curl -L 'https://github.com/vectordotdev/vector/releases/download/v0.53.0/vector-0.53.0-x86_64-unknown-linux-gnu.tar.gz' -o /tmp/vector.tar.gz
cd /tmp && tar -xzf vector.tar.gz
scp vector-x86_64-unknown-linux-gnu/bin/vector aliyun:/tmp/
ssh aliyun "sudo cp /tmp/vector /usr/local/bin/ && sudo chmod +x /usr/local/bin/vector"
```

### 配置文件

位置: `mihomo/ansible/roles/mihomo/templates/vector.yaml.j2`

```yaml
data_dir: /var/lib/vector

api:
  enabled: true
  address: 127.0.0.1:8686

sources:
  envoy_access_log:
    type: file
    include:
      - /var/log/envoy/access.log
    read_from: beginning
    ignore_older_secs: 86400

transforms:
  parse_json:
    type: remap
    inputs:
      - envoy_access_log
    source: |
      parsed = parse_json!(.message)
      . = parsed
      .host = get_hostname!()
      .container_name = "envoy"
      if !exists(.timestamp) {
        .timestamp = now()
      }
      .message = to_string!(.method) + " " + to_string!(.path) + " " + to_string!(.response_code)

sinks:
  victorialogs:
    type: elasticsearch
    inputs:
      - parse_json
    endpoints:
      - "http://gtr.tail414c32.ts.net:8429/insert/elasticsearch/"
    mode: bulk
    api_version: v8
    healthcheck:
      enabled: false
    query:
      _msg_field: message
      _time_field: timestamp
      _stream_fields: host,container_name
```

### Systemd Service

```bash
sudo useradd -r -s /usr/sbin/nologin vector
sudo mkdir -p /var/lib/vector
sudo chown vector:vector /var/lib/vector

# 修改 service 文件中的路径
sudo sed -i 's|/usr/bin/vector|/usr/local/bin/vector|g' /etc/systemd/system/vector.service

sudo systemctl daemon-reload
sudo systemctl enable vector
sudo systemctl start vector
```

## Ansible 部署

### 变量配置

位置: `mihomo/ansible/group_vars/aliyun/public.yml`

```yaml
# VictoriaLogs OTLP endpoint (via Tailscale)
victorialogs_host: "gtr.tail414c32.ts.net"
victorialogs_port: 8429

# VictoriaTrace OTLP gRPC endpoint (via Tailscale)
victoriatrace_host: "gtr.tail414c32.ts.net"
victoriatrace_port: 9429

# Vector version
vector_version: "v0.53.0"
```

### 部署命令

```bash
cd mihomo/ansible
ansible-playbook -i inventory-aliyun.ini deploy-aliyun.yml
```

## 查询示例

### VictoriaLogs 查询

```bash
# 查询阿里云 ECS 日志
curl 'http://gtr:8429/select/logsql/query?query=host:iZf8z8qpzl0oqrzqf1y9t1Z'

# 查询特定路径
curl 'http://gtr:8429/select/logsql/query?query=path:/node_exporter/metrics'

# 查询错误响应
curl 'http://gtr:8429/select/logsql/query?query=response_code:4*'
```

### VictoriaTraces 查询

访问 Web UI: `http://gtr:9428/select/vmui`

通过 trace_id 查询日志：
```bash
curl 'http://gtr:8429/select/logsql/query?query=trace_id:77196e8f0b34e19bf1f3228085a383aa'
```

## 故障排查

### 检查 Tailscale 连接

```bash
# 在 Aliyun 上
ping gtr.tail414c32.ts.net
curl http://gtr.tail414c32.ts.net:8429/health
curl http://gtr.tail414c32.ts.net:9428/health
```

### 检查 Envoy Cluster 状态

```bash
# 在 Aliyun 上
curl http://localhost:8001/clusters | grep victoriatrace
curl http://localhost:8001/clusters | grep -A5 victorialogs
```

### 检查 Vector 状态

```bash
# 在 Aliyun 上
sudo systemctl status vector
sudo journalctl -u vector -n 50
curl http://localhost:8686/health
```

### 检查日志文件

```bash
# 检查 Envoy 日志
tail -f /var/log/envoy/access.log | jq .

# 检查日志是否有 trace_id
tail /var/log/envoy/access.log | jq '.trace_id'
```

## 参考链接

- [Envoy OpenTelemetry Tracing](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/observability/tracing.html)
- [Vector Elasticsearch Sink](https://vector.dev/docs/reference/configuration/sinks/elasticsearch/)
- [VictoriaLogs Elasticsearch API](https://docs.victoriametrics.com/victorialogs/data-ingestion/#elasticsearch-bulk-api)
- [VictoriaTraces OTLP](https://docs.victoriametrics.com/victoriatraces/)
- [Tailscale ACL](https://tailscale.com/kb/1018/acls/)

---

最后更新: 2026-02-11
