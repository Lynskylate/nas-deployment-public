# VictoriaLogs Service - Runbook

## 服务概述

VictoriaLogs 是一个高性能的日志存储和查询系统，用于集中化存储和分析日志数据。

## 服务信息

| 项目 | 值 |
|------|-----|
| 服务名称 | victorialogs |
| 运行用户 | victorialogs |
| HTTP 端口 | 8429 |
| 数据目录 | /var/lib/victorialogs/data |
| 二进制路径 | /usr/local/victorialogs/victoria-logs-prod |

## 配置文件

| 文件路径 | 说明 |
|---------|------|
| /etc/systemd/system/victorialogs.service | Systemd 服务单元文件 |

## 服务管理

```bash
# 连接到服务器
ssh gtr

# 查看服务状态
systemctl status victorialogs

# 启动服务
sudo systemctl start victorialogs

# 停止服务
sudo systemctl stop victorialogs

# 重启服务
sudo systemctl restart victorialogs

# 查看服务日志
journalctl -u victorialogs -f

# 查看最近100行日志
journalctl -u victorialogs -n 100
```

## Web 访问

- **VictoriaLogs UI**: http://gtr:8429
- **Health Check**: http://gtr:8429/health

## 数据摄入

VictoriaLogs 接受多种格式的日志摄入：

### Elasticsearch API (Vector 使用)

```bash
# 端点
http://localhost:8429/insert/elasticsearch/

# Vector 配置示例
sinks:
  vlogs:
    type: "elasticsearch"
    endpoints:
      - "http://localhost:8429/insert/elasticsearch/"
```

### LogsQL 查询语法

VictoriaLogs 使用 LogsQL 查询语言：

```bash
# 搜索包含特定关键词的日志
_search="error"

# 按时间范围过滤
_time_range:1h

# 按流字段过滤
{stream_field="value"}

# 组合查询
_search:"error" _time_range:24h
```

## 与 Grafana 集成

VictoriaLogs 通过 Grafana 插件进行可视化：

1. 安装 VictoriaLogs 数据源插件
2. 配置数据源：http://localhost:8429
3. 使用 LogsQL 查询创建面板

## 日志来源

当前系统中，Vector 从以下位置收集日志并发送到 VictoriaLogs：

- `/var/log/envoy/access.log` - Envoy 代理访问日志

## 故障排查

### 服务无法启动

```bash
# 检查服务状态
systemctl status victorialogs

# 查看详细日志
journalctl -u victorialogs -n 50 --no-pager

# 检查端口占用
ss -tulnp | grep 8429

# 检查数据目录权限
ls -la /var/lib/victorialogs/
```

### 日志未收到

检查 Vector 服务状态：
```bash
systemctl status vector
journalctl -u vector -f
```

检查 Vector 配置：
```bash
cat /etc/vector/vector.yaml
```

## 数据备份

```bash
# 备份数据目录
sudo tar -czf victorialogs-backup-$(date +%Y%m%d).tar.gz /var/lib/victorialogs/data

# 恢复数据
sudo tar -xzf victorialogs-backup-YYYYMMDD.tar.gz -C /
```

## 启动参数

当前启动参数（在 systemd 服务文件中）：

| 参数 | 当前值 | 说明 |
|-----|-------|------|
| -storageDataPath | /var/lib/victorialogs/data | 数据存储目录 |
| -httpListenAddr | :8429 | HTTP监听地址 |

## 常见警告解释

```
unsupported path requested: "/opentelemetry.proto.collector.logs.v1.LogsService/Export"
```

此警告表示有客户端尝试使用 OpenTelemetry 协议发送日志，但当前配置的 Vector 使用 Elasticsearch API。可以忽略或调整 Vector 配置。
