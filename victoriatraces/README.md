# VictoriaTraces Service - Runbook

## 服务概述

VictoriaTraces 是一个高性能的分布式追踪存储和查询系统，用于存储和分析 OpenTelemetry traces 数据。

## 服务信息

| 项目 | 值 |
|------|-----|
| 服务名称 | victoriatraces |
| 运行用户 | victoriatraces |
| HTTP 端口 | 9428 |
| 数据目录 | /var/lib/victoriatraces/data |
| 二进制路径 | /usr/local/victoriatraces/victoria-traces-prod |

## 快速部署

### Ansible 部署 (推荐)

```bash
cd victoriatraces/ansible
ansible-playbook -i inventory.ini deploy.yml
```

### Shell 脚本部署

```bash
cd victoriatraces
chmod +x install.sh
./install.sh
```

## 配置文件

| 文件路径 | 说明 |
|---------|------|
| /etc/systemd/system/victoriatraces.service | Systemd 服务单元文件 |

## 服务管理

```bash
# 连接到服务器
ssh gtr

# 查看服务状态
systemctl status victoriatraces

# 启动服务
sudo systemctl start victoriatraces

# 停止服务
sudo systemctl stop victoriatraces

# 重启服务
sudo systemctl restart victoriatraces

# 查看服务日志
journalctl -u victoriatraces -f

# 查看最近100行日志
journalctl -u victoriatraces -n 100
```

## Web 访问

- **VictoriaTraces UI**: http://gtr:9428/vmui
- **Health Check**: http://gtr:9428/health
- **Metrics**: http://gtr:9428/metrics

## 数据摄入

VictoriaTraces 支持 OpenTelemetry OTLP 协议：

### OTLP/HTTP

```bash
# 端点
http://gtr:9428/insert/opentelemetry/v1/traces

# 示例
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[...]}' \
  http://gtr:9428/insert/opentelemetry/v1/traces
```

### OpenTelemetry Collector 配置

```yaml
exporters:
  otlphttp/victoriatraces:
    endpoint: http://gtr:9428/insert/opentelemetry

service:
  pipelines:
    traces:
      exporters: [otlphttp/victoriatraces]
```

## 数据查询

### 内置 VMUI

访问 http://gtr:9428/vmui 浏览和搜索 traces。

### Jaeger 兼容 API

VictoriaTraces 提供与 Jaeger 兼容的查询 API：

```bash
# Jaeger 查询端点
http://gtr:9428/select/jaeger
```

### Grafana 集成

1. 添加 **Jaeger** 数据源
2. 配置 URL: `http://gtr:9428/select/jaeger`
3. 在 Explore 中查询 traces

## 故障排查

### 服务无法启动

```bash
# 检查服务状态
systemctl status victoriatraces

# 查看详细日志
journalctl -u victoriatraces -n 50 --no-pager

# 检查端口占用
ss -tulnp | grep 9428

# 检查数据目录权限
ls -la /var/lib/victoriatraces/
```

### 数据未收到

1. 检查 OTLP 导出器配置
2. 确认网络连通性
3. 查看服务日志

```bash
journalctl -u victoriatraces -f
```

### 查询返回空结果

1. 确认数据已成功写入
2. 检查时间范围
3. 验证查询语法

## 数据备份

```bash
# 备份数据目录
sudo tar -czf victoriatraces-backup-$(date +%Y%m%d).tar.gz /var/lib/victoriatraces/data

# 恢复数据
sudo tar -xzf victoriatraces-backup-YYYYMMDD.tar.gz -C /
```

## 启动参数

| 参数 | 当前值 | 说明 |
|-----|-------|------|
| -storageDataPath | /var/lib/victoriatraces/data | 数据存储目录 |
| -httpListenAddr | :9428 | HTTP监听地址 |

修改后执行：
```bash
sudo systemctl daemon-reload
sudo systemctl restart victoriatraces
```

## 监控

VictoriaTraces 在 `http://gtr:9428/metrics` 暴露 Prometheus 格式的指标。

推荐 Grafana 仪表板:
- VictoriaTraces single-node (ID: 24136)

## 卸载

```bash
# 停止并禁用服务
sudo systemctl stop victoriatraces
sudo systemctl disable victoriatraces

# 删除服务文件
sudo rm /etc/systemd/system/victoriatraces.service
sudo systemctl daemon-reload

# 删除用户和组
sudo userdel victoriatraces
sudo groupdel victoriatraces

# 删除二进制文件和数据
sudo rm -rf /usr/local/victoriatraces
sudo rm -rf /var/lib/victoriatraces
```
