# Envoy Proxy Service - Runbook

## 服务概述

Envoy 是一个高性能的分布式代理，用于作为 API Gateway、反向代理和负载均衡器。

## 服务信息

| 项目 | 值 |
|------|-----|
| 服务名称 | envoy |
| 运行用户 | envoy |
| HTTP 端口 | 80 (对外) |
| Admin 端口 | 9901 |
| 二进制路径 | /usr/local/envoy/envoy |

## 配置文件

| 文件路径 | 说明 |
|---------|------|
| /etc/systemd/system/envoy.service | Systemd 服务单元文件 |
| /etc/envoy/envoy.yaml | 静态配置文件 |
| /etc/envoy/dynamic_config/lds.yaml | 监听器发现服务配置 |
| /etc/envoy/dynamic_config/cds.yaml | 集群发现服务配置 |
| /etc/envoy/dynamic_config/rds.yaml | 路由发现服务配置 |

## 日志文件

| 文件路径 | 说明 |
|---------|------|
| /var/log/envoy/proxy.log | Envoy 代理日志 |
| /var/log/envoy/access.log | HTTP 访问日志 |

## 服务管理

```bash
# 连接到服务器
ssh gtr

# 查看服务状态
systemctl status envoy

# 启动服务
sudo systemctl start envoy

# 停止服务
sudo systemctl stop envoy

# 重启服务
sudo systemctl restart envoy

# 重新加载配置（HUP信号）
sudo systemctl reload envoy

# 查看服务日志
journalctl -u envoy -f

# 查看访问日志
sudo tail -f /var/log/envoy/access.log
```

## Web 访问

- **Envoy Admin UI**: http://gtr:9901
- **代理服务**: http://gtr:80

## Admin 接口常用端点

```bash
# 查看所有统计信息
curl http://localhost:9901/stats

# 查看集群状态
curl http://localhost:9901/clusters

# 查看监听器状态
curl http://localhost:9901/listeners

# 查看配置（已生效）
curl http://localhost:9901/config_dump

# 热重载配置
curl -X POST http://localhost:9901/reload-config

# 退出进程（优雅关闭）
curl -X POST http://localhost:9901/quitquitquit

# Prometheus 格式指标
curl http://localhost:9901/stats/prometheus
```

## 配置说明

### 静态配置 (envoy.yaml)

```yaml
node:
  id: gtr-local          # 节点标识
  cluster: gtr-cluster   # 集群名称

admin:
  access_log_path: /var/log/envoy/access.log
  address:
    socket_address:
      address: 0.0.0.0
      port_value: 9901   # Admin 端口

dynamic_resources:
  lds_config:            # 监听器动态配置
    path_config_source:
      path: /etc/envoy/dynamic_config/lds.yaml
  cds_config:            # 集群动态配置
    path_config_source:
      path: /etc/envoy/dynamic_config/cds.yaml
```

### 后端服务集群

Envoy 配置了以下后端集群：

| 集群名称 | 后端地址 | 说明 |
|---------|---------|------|
| admin_service | 127.0.0.1:9901 | Envoy Admin 接口 |
| grafana_service | 127.0.0.1:3000 | Grafana |
| victoriametrics_service | 127.0.0.1:8428 | VictoriaMetrics |
| logs_service | 127.0.0.1:8429 | VictoriaLogs |
| web_service | httpbin.org:80 | 外部测试服务 |

### 监听器配置

当前配置的监听器：

- **listener_0** (0.0.0.0:80)
  - HTTP 连接管理器
  - 访问日志输出到 `/var/log/envoy/access.log`
  - 同时发送 OpenTelemetry 日志到 VictoriaLogs
  - 使用动态路由 (RDS)

## 日志处理流程

1. **访问日志**: 请求日志写入 `/var/log/envoy/access.log`
2. **Vector**: 从文件读取日志并解析
3. **VictoriaLogs**: 接收并存储处理后的日志

## 动态配置重载

修改动态配置文件后，Envoy 会自动检测并重新加载：

```bash
# 编辑 LDS 配置
sudo vim /etc/envoy/dynamic_config/lds.yaml

# 编辑 CDS 配置
sudo vim /etc/envoy/dynamic_config/cds.yaml

# 编辑 RDS 配置
sudo vim /etc/envoy/dynamic_config/rds.yaml

# Envoy 会自动检测文件变化并重载
# 查看重载状态
curl http://localhost:9901/config_dump | jq '.configs[2].dynamic_route_configs'
```

## 故障排查

### 服务无法启动

```bash
# 检查服务状态
systemctl status envoy

# 查看详细日志
journalctl -u envoy -n 50 --no-pager

# 检查配置文件语法
/usr/local/envoy/envoy --mode validate -c /etc/envoy/envoy.yaml

# 检查端口占用
ss -tulnp | grep -E ':(80|9901)'

# 测试配置
sudo -u envoy /usr/local/envoy/envoy -c /etc/envoy/envoy.yaml --log-level debug
```

### 503/Upstream Failure

```bash
# 检查后端服务状态
systemctl status grafana victoriametrics victorialogs

# 检查集群健康状态
curl http://localhost:9901/clusters | jq '.cluster_statuses'

# 查看统计信息
curl http://localhost:9901/stats | grep -E 'upstream|cluster'
```

### 路由不生效

```bash
# 检查当前路由配置
curl http://localhost:9901/config_dump | jq '.configs[2].dynamic_route_configs'

# 查看 RDS 配置文件
cat /etc/envoy/dynamic_config/rds.yaml

# 检查监听器配置
curl http://localhost:9901/listeners
```

## 性能监控

通过 VictoriaMetrics 监控 Envoy：

```promql
# 查看 Envoy 自身指标
curl http://localhost:9901/stats/prometheus

# 常用指标示例
envoy_cluster_upstream_cx_total        # 上游连接总数
envoy_cluster_upstream_rq_total        # 上游请求总数
envoy_cluster_upstream_rq_2xx          # 2xx 响应数
envoy_cluster_upstream_rq_5xx          # 5xx 响应数
envoy_server_memory_heap_size          # 堆内存使用
```

## 配置示例

### 添加新的后端服务

1. 编辑 CDS 配置，添加新集群：

```yaml
# /etc/envoy/dynamic_config/cds.yaml
resources:
  - "@type": type.googleapis.com/envoy.config.cluster.v3.Cluster
    name: new_service
    connect_timeout: 0.25s
    type: STATIC
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: new_service
      endpoints:
        - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: 127.0.0.1
                    port_value: 8080
```

2. 编辑 RDS 配置，添加路由规则

3. Envoy 会自动重载配置

## 安全建议

1. **限制 Admin 访问**: Admin 端口不应暴露到公网
2. **TLS 终止**: 在生产环境使用 HTTPS
3. **访问控制**: 配置适当的 IP 白名单
4. **日志审计**: 定期检查访问日志
