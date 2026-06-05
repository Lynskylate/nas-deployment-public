# GTR 服务文档

这是运行在 `gtr` 服务器上的服务文档集合。

## 服务器信息

| 项目 | 值 |
|------|-----|
| 主机名 | gtr |
| OS | Ubuntu 22.04 LTS |
| 内核 | Linux 5.15.0-164-generic |
| 架构 | x86_64 |

## 服务概览

| 服务 | 端口 | 目录 | 用途 |
|------|------|------|------|
| Grafana | 3000 | ./grafana | 可视化监控仪表板 |
| VictoriaMetrics | 8428 | ./victoriametrics | 时序指标数据库 |
| VictoriaLogs | 8429 | ./victorialogs | 日志存储和分析 |
| Envoy | 80, 9901 | ./envoy | API 网关和反向代理 |

## 服务架构

```
                    ┌─────────────────────────────────────────┐
                    │              Envoy (Port 80)            │
                    │         API Gateway / Proxy             │
                    └─────────────────┬───────────────────────┘
                                      │
                ┌─────────────────────┼─────────────────────┐
                │                     │                     │
                ▼                     ▼                     ▼
        ┌─────────────┐      ┌──────────────┐      ┌──────────────┐
        │  Grafana    │      │ VictoriaLogs │      │Victoriametrics│
        │   Port 3000 │      │   Port 8429  │      │   Port 8428   │
        └─────────────┘      └──────┬───────┘      └──────────────┘
                                    │
                            ┌───────▼────────┐
                            │  Vector        │
                            │ (日志收集)      │
                            └────────────────┘
```

## 快速链接

- [Grafana Runbook](./grafana/README.md) - 监控可视化平台
- [VictoriaMetrics Runbook](./victoriametrics/README.md) - 时序数据库
- [VictoriaLogs Runbook](./victorialogs/README.md) - 日志数据库
- [Envoy Runbook](./envoy/README.md) - API 网关
- [Project Runtime](./project-runtime/README.md) - rootless Podman 项目运行时基线
- [K3s Migration Baseline](./k3s/README.md) - K3s / Argo / Sealed Secrets / Tailscale Operator 迁移入口

## 常用命令

### 项目运行时基线

```bash
cd edge/ansible

# 安装 gtr 项目运行时基线
ansible-playbook -i inventory-edge.ini deploy-gtr-project-runtime.yml

# 验证 gtr 项目运行时基线
ansible-playbook -i inventory-edge.ini verify-gtr-project-runtime.yml
```

### 服务状态总览

```bash
# 连接到服务器
ssh gtr

# 查看所有服务状态
systemctl status envoy grafana victoriametrics victorialogs

# 查看监听端口
ss -tulnp | grep -E ':(80|3000|8428|8429|9901)'

# 查看资源使用
ps aux | grep -E 'envoy|grafana|victoria'
```

### 日志查看

```bash
# 实时查看所有服务日志
journalctl -f -u envoy -u grafana -u victoriametrics -u victorialogs

# 查看访问日志
tail -f /var/log/envoy/access.log
```

## 服务依赖关系

1. **Envoy** 是入口，代理所有外部请求
2. **Vector** 收集 Envoy 日志并发送到 VictoriaLogs
3. **VictoriaMetrics** 抓取各服务指标
4. **Grafana** 从 VictoriaMetrics 和 VictoriaLogs 读取数据进行展示

## 监控访问

- **Grafana**: http://gtr:3000
- **VictoriaMetrics**: http://gtr:8428
- **VictoriaLogs**: http://gtr:8429
- **Envoy Admin**: http://gtr:9901

## 数据流

### 指标数据流
```
各服务 (node_exporter, envoy等)
    ↓ (Prometheus 格式)
VictoriaMetrics (抓取和存储)
    ↓ (查询)
Grafana (可视化)
```

### 日志数据流
```
Envoy (访问日志)
    ↓ (文件)
Vector (解析和转换)
    ↓ (Elasticsearch API)
VictoriaLogs (存储)
    ↓ (LogsQL 查询)
Grafana (展示)
```

## 故障排查流程

### 服务不可访问

1. 检查服务是否运行: `systemctl status <service>`
2. 检查端口是否监听: `ss -tulnp | grep <port>`
3. 检查防火墙规则
4. 查看服务日志: `journalctl -u <service> -n 100`

### 数据未更新

1. 检查 VictoriaMetrics 抓取目标: `curl http://localhost:8428/api/v1/targets`
2. 检查 Vector 日志: `journalctl -u vector -f`
3. 检查 VictoriaLogs 摄入: 查询日志是否有新数据

## 备份策略

建议定期备份以下目录：

```bash
# VictoriaMetrics 数据
/var/lib/victoriametrics/data

# VictoriaLogs 数据
/var/lib/victorialogs/data

# Grafana 数据（含仪表板、用户等）
/usr/local/grafana/data

# Envory 配置
/etc/envoy/
```

## 联系信息

如有问题，请联系系统管理员。
