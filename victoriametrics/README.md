# VictoriaMetrics Service - Runbook

## 服务概述

VictoriaMetrics 是一个高性能的时序数据库，用于存储和查询监控指标数据。

## 服务信息

| 项目 | 值 |
|------|-----|
| 服务名称 | victoriametrics |
| 运行用户 | victoriametrics |
| HTTP 端口 | 8428 |
| 数据保留期 | 360小时 (15天) |
| 数据目录 | /var/lib/victoriametrics/data |
| 二进制路径 | /usr/local/victoriametrics/victoria-metrics-prod |

## 配置文件

| 文件路径 | 说明 |
|---------|------|
| /etc/systemd/system/victoriametrics.service | Systemd 服务单元文件 |
| /usr/local/victoriametrics/victoriametrics_sd.yaml | Prometheus 抓取配置 |

## 服务管理

```bash
# 连接到服务器
ssh gtr

# 查看服务状态
systemctl status victoriametrics

# 启动服务
sudo systemctl start victoriametrics

# 停止服务
sudo systemctl stop victoriametrics

# 重启服务
sudo systemctl restart victoriametrics

# 重新加载配置
sudo systemctl reload victoriametrics

# 查看服务日志
journalctl -u victoriametrics -f

# 查看最近100行日志
journalctl -u victoriametrics -n 100
```

## Web 访问

- **VictoriaMetrics UI**: http://gtr:8428
- **Metrics 端点**: http://gtr:8428/metrics
- **Health Check**: http://gtr:8428/health

## 抓取目标配置

当前配置的抓取目标 (victoriametrics_sd.yaml):

1. **victoriametrics** - 本地VM服务和其他节点
   - 127.0.0.1:8428 (VM自身)
   - 127.0.0.1:9100/metrics (本机node_exporter)
   - 192.168.31.58:9100/metrics (局域网节点)
   - 142.171.205.19:9100/metrics (公网节点)

2. **aliyun_envoy** - 阿里云Envoy服务
   - 47.120.46.128/stats/prometheus
   - 47.120.46.128/node_exporter/metrics

3. **local_envoy** - 本地Envoy
   - 127.0.0.1:9901/stats/prometheus

## 常用查询示例

```promql
# 查看所有指标
http://gtr:8428/api/v1/label/__name__/values

# 查询特定指标
http://gtr:8428/api/v1/query?query=up

# 查询范围数据
http://gtr:8428/api/v1/query_range?query=up&start=...&end=...&step=15s
```

## 故障排查

### 服务无法启动

```bash
# 检查服务状态
systemctl status victoriametrics

# 查看详细日志
journalctl -u victoriametrics -n 50 --no-pager

# 检查端口占用
ss -tulnp | grep 8428

# 检查数据目录权限
ls -la /var/lib/victoriametrics/
```

### 抓取目标失败

查看日志中的警告信息：
```bash
journalctl -u victoriametrics -f | grep "cannot scrape target"
```

常见原因：
- 目标节点未运行 node_exporter
- 网络连接问题
- 防火墙阻止

## 数据备份

```bash
# 备份数据目录
sudo tar -czf victoriametrics-backup-$(date +%Y%m%d).tar.gz /var/lib/victoriametrics/data

# 恢复数据
sudo tar -xzf victoriametrics-backup-YYYYMMDD.tar.gz -C /
```

## 性能调优

启动参数说明（在 systemd 服务文件中）：

| 参数 | 当前值 | 说明 |
|-----|-------|------|
| -storageDataPath | /var/lib/victoriametrics/data | 数据存储目录 |
| -retentionPeriod | 360h | 数据保留时间 |
| -httpListenAddr | :8428 | HTTP监听地址 |
| -promscrape.config | victoriametrics_sd.yaml | 抓取配置文件 |

修改后执行：
```bash
sudo systemctl daemon-reload
sudo systemctl restart victoriametrics
```
