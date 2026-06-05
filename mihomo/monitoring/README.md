# Mihomo 监控集成

将 Mihomo 代理的指标和日志集成到现有的 VictoriaMetrics 和 VictoriaLogs 基础设施中。

## 架构概述

```
┌─────────────────────────────────────────────────────────────────┐
│                         GTR 服务器                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────┐          ┌──────────────────┐                      │
│  │ Mihomo  │          │ Metrics Collector│                      │
│  │ :9090   │ ────────▶│ (systemd timer)  │                      │
│  │ :7890   │ API      │ :15s interval    │                      │
│  └─────────┘          └────────┬─────────┘                      │
│                                │                                │
│                                ▼                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │               VictoriaMetrics :8428                      │   │
│  │  - mihomo_traffic_upload_bytes                          │   │
│  │  - mihomo_traffic_download_bytes                        │   │
│  │  - mihomo_connections_active                            │   │
│  │  - mihomo_proxy_up                                      │   │
│  │  - mihomo_rules_total                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌─────────┐          ┌──────────────────┐                     │
│  │ Mihomo  │ Logs     │   Vector (old)   │                     │
│  │ journal │ ────────▶│  (parse journald)│                     │
│  └─────────┘          └────────┬─────────┘                     │
│                                │                                │
│                                ▼                                │
│  ┌─────────┐          ┌──────────────────┐                     │
│  │ Mihomo  │ WS Logs  │   WS Collector   │                     │
│  │ :9090   │ ────────▶│   (Python)       │                     │
│  │ /logs   │ realtime └────────┬─────────┘                     │
│  └─────────┘                   │                                │
│                                ▼                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│ │                VictoriaLogs :8429                         │   │
│ │  - connection logs (client, destination, proxy)           │   │
│ │  - rule match logs (type, domain, proxy)                │   │
│ │  - error logs                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────┐
                          │     Grafana     │
                          │    :3000        │
                          │  可视化仪表板    │
                          └─────────────────┘
```

## 收集的指标

### 指标 (VictoriaMetrics)

| 指标名称 | 类型 | 描述 |
|---------|------|------|
| `mihomo_traffic_upload_bytes` | gauge | 总上传字节数 |
| `mihomo_traffic_download_bytes` | gauge | 总下载字节数 |
| `mihomo_connections_active` | gauge | 当前活跃连接数 |
| `mihomo_connections_by_proxy` | gauge | 按代理类型分组的连接数 |
| `mihomo_proxy_up` | gauge | 代理可用性状态 (1=可用, 0=不可用) |
| `mihomo_proxy_selected` | gauge | 代理是否被当前选中 |
| `mihomo_rules_total` | gauge | 规则总数 |
| `mihomo_rules_by_type` | gauge | 按类型分组的规则数 |
| `mihomo_provider_up` | gauge | 代理提供者可用性 |
| `mihomo_provider_proxy_count` | gauge | 代理提供者中的节点数量 |
| `mihomo_memory_bytes` | gauge | 内存使用量 |
| `mihomo_scrape_success` | gauge | 指标采集是否成功 |

### 日志 (VictoriaLogs)

| 日志类型 | 字段 |
|---------|------|
| 连接日志 | `log_type`, `protocol`, `client_ip`, `dest_host`, `dest_port`, `rule_type`, `rule_pattern`, `proxy` |
| 通用日志 | `log_type`, `log_level`, `_msg` |

## 部署方式

### 方式一：一键安装脚本

```bash
cd mihomo/monitoring

# 部署
chmod +x install.sh
./install.sh deploy

# 验证
./install.sh verify

# 清理
./install.sh clean
```

### 方式二：Ansible Playbook

```bash
cd mihomo/monitoring/ansible

# 编辑目标服务器
nano inventory.ini

# 部署
ansible-playbook -i inventory.ini deploy.yml

# 仅检查模式（不执行）
ansible-playbook -i inventory.ini deploy.yml --check
```

### 方式三：手动部署

```bash
# 1. SSH 到 gtr 服务器
ssh gtr

# 2. 创建日志目录
sudo mkdir -p /var/log/mihomo
sudo chown mihomo:mihomo /var/log/mihomo

# 3. 安装依赖
sudo apt install jq

# 4. 复制文件（从 templates 目录）
# - mihomo-metrics.sh → /usr/local/bin/mihomo-metrics.sh
# - mihomo-metrics.service → /etc/systemd/system/
# - mihomo-metrics.timer → /etc/systemd/system/
# - vector-mihomo.yaml → /etc/vector/mihomo.yaml

# 5. 更新 Vector 服务配置
sudo vi /etc/systemd/system/vector.service
# 在 ExecStart 行添加: --config /etc/vector/mihomo.yaml

# 6. 重载并启动服务
sudo systemctl daemon-reload
sudo systemctl enable mihomo-metrics.timer
sudo systemctl start mihomo-metrics.timer
sudo systemctl restart vector
```

## 验证部署

### 1. 检查服务状态

```bash
ssh gtr

# 检查 Mihomo 服务
systemctl status mihomo

# 检查指标收集器定时器
systemctl status mihomo-metrics.timer
systemctl list-timers mihomo-metrics.timer

# 检查最近一次指标采集
journalctl -u mihomo-metrics -n 1

# 检查 Vector 服务
systemctl status vector
journalctl -u vector -f | grep mihomo
```

### 2. 验证指标 (VictoriaMetrics)

```bash
# 查询指标是否存在
curl -s 'http://gtr:8428/api/v1/label/__name__/values' | jq '.[]' | grep mihomo

# 查询特定指标
curl -s 'http://gtr:8428/api/v1/query?query=mihomo_scrape_success' | jq .

# 查看流量指标
curl -s 'http://gtr:8428/api/v1/query?query=mihomo_traffic_download_bytes' | jq .
```

### 3. 验证日志 (VictoriaLogs)

```bash
# 查询 mihomo 日志
curl -G http://gtr:8429/select/log/sql/query \
  --data-urlencode 'query={service="mihomo"} LIMIT 10' | jq .

# 查询特定类型的日志
curl -G http://gtr:8429/select/log/sql/query \
  --data-urlencode 'query={service="mihomo", log_type="connection"} LIMIT 10' | jq .

# 统计日志数量
curl -G http://gtr:8429/select/log/sql/query \
  --data-urlencode 'query=_count:{service="mihomo"}' | jq .
```

## Grafana Dashboard 查询示例

### PromQL 查询 (指标)

```promql
# 实时流量速率 (字节/秒)
rate(mihomo_traffic_download_bytes{server="gtr"}[5m])
rate(mihomo_traffic_upload_bytes{server="gtr"}[5m])

# 活跃连接数
mihomo_connections_active{server="gtr"}

# 代理可用性 (按分组)
mihomo_proxy_up{server="gtr", proxy_group="Auto"}

# 规则总数
mihomo_rules_total{server="gtr"}

# 按类型分组的规则数
mihomo_rules_by_type{server="gtr"}

# 内存使用
mihomo_memory_bytes{server="gtr"}

# 采集成功率
mihomo_scrape_success{server="gtr"}
```

### LogsQL 查询 (日志)

```logsql
# 所有 mihomo 日志
{service="mihomo"}

# 连接日志
{service="mihomo", log_type="connection"}

# 特定代理的使用日志
{service="mihomo"} ~= "Auto"

# 错误日志
{service="mihomo", log_level="ERROR"}

# 最近 1 小时的日志
{service="mihomo"} _time_range:1h

# 按代理分组统计
_count_by_time(5m, {service="mihomo"}) group by proxy_used
```

## 故障排查

### 指标未收集

```bash
# 检查 API 连接
curl -s "http://127.0.0.1:9090/traffic?secret=<mihomo-secret-from-private-vault>" | jq .

# 手动运行收集器脚本
sudo -u nobody /usr/local/bin/mihomo-metrics.sh

# 检查定时器
systemctl status mihomo-metrics.timer
systemctl list-timers | grep mihomo
```

### 日志未收集

```bash
# 检查 Vector 配置
vector validate /etc/vector/mihomo.yaml

# 查看 Vector 日志
journalctl -u vector -f

# 检查 systemd journal 是否有 mihomo 日志
journalctl -u mihomo -n 20
```

### API 认证失败

如果 Mihomo API 返回 "Unauthorized"，检查：

1. Secret 是否正确：`<mihomo-secret-from-private-vault>`
2. Mihomo 配置文件中的 `secret` 字段
3. API 端点是否可访问：`curl http://127.0.0.1:9090`

## 文件位置

| 文件 | 服务器路径 |
|------|-----------|
| 指标收集脚本 | `/usr/local/bin/mihomo-metrics.sh` |
| Systemd 服务 | `/etc/systemd/system/mihomo-metrics.service` |
| Systemd 定时器 | `/etc/systemd/system/mihomo-metrics.timer` |
| WS 日志收集器 | `/usr/local/bin/mihomo-logs-collector.py` |
| WS 日志服务 | `/etc/systemd/system/mihomo-logs-collector.service` |
| Vector 配置 | `/etc/vector/mihomo.yaml` |
| 验证脚本 | `/usr/local/bin/mihomo-monitoring-check.sh` |

## 依赖项

- Mihomo API secret: `<mihomo-secret-from-private-vault>`
- VictoriaMetrics import API: `http://127.0.0.1:8428/api/v1/import/prometheus`
- VictoriaLogs insert API: `http://127.0.0.1:8429/insert/jsonline`
- `jq` - JSON 解析工具
- `curl` - HTTP 客户端
- `python3-websocket-client` - WebSocket 客户端

## 相关链接

- [Mihomo REST API 文档](https://github.com/MetaCubeX/mihomo-meta/wiki/API-Dashboard)
- [VictoriaMetrics 文档](https://docs.victoriametrics.com/)
- [VictoriaLogs 文档](https://docs.victoriametrics.com/VictoriaLogs.html)
- [Vector 文档](https://vector.dev/docs/)
