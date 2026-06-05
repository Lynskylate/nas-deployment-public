# Node Exporter - 运维手册

## 服务概述

Node Exporter 是 Prometheus 官方提供的系统指标采集器，用于收集 Linux 系统的硬件和操作系统指标。

## 服务信息

| 项目 | 值 |
|------|-----|
| 服务名称 | node_exporter |
| 运行用户 | node_exporter |
| HTTP 端口 | 9100 |
| 二进制路径 | /usr/local/node_exporter/node_exporter |
| 版本 | 1.8.2 |

## 快速部署

```bash
# 克隆或进入仓库目录
cd /path/to/gtr-services

# 执行部署脚本（在 gtr 服务器上）
cd node_exporter
chmod +x install.sh
./install.sh
```

部署脚本会自动完成以下操作：
1. 创建 node_exporter 系统用户和组
2. 下载并安装二进制文件
3. 创建 systemd 服务单元
4. 配置防火墙规则（如启用）
5. 启动并启用服务

## 服务管理

```bash
# 连接到服务器
ssh gtr

# 查看服务状态
systemctl status node_exporter

# 启动服务
sudo systemctl start node_exporter

# 停止服务
sudo systemctl stop node_exporter

# 重启服务
sudo systemctl restart node_exporter

# 查看服务日志
journalctl -u node_exporter -f

# 查看最近100行日志
journalctl -u node_exporter -n 100
```

## 访问端点

| 端点 | URL | 说明 |
|------|-----|------|
| Metrics | http://gtr:9100/metrics | Prometheus 指标格式 |
| Health | http://gtr:9100/ | 基本健康检查 |

## 收集的指标类别

Node Exporter 默认启用的收集器：

| 收集器 | 说明 |
|--------|------|
| cpu | CPU 使用情况 |
| diskstats | 磁盘 I/O 统计 |
| filesystem | 文件系统使用情况 |
| loadavg | 系统负载 |
| meminfo | 内存信息 |
| netdev | 网络接口统计 |
| stat | 系统统计信息 |
| time | 当前时间 |
| uname | 系统信息 |
| vmstat | 虚拟内存统计 |

## 常用查询示例

```promql
# CPU 使用率
100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# 内存使用率
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100

# 磁盘使用率
(node_filesystem_size_bytes - node_filesystem_avail_bytes) / node_filesystem_size_bytes * 100

# 系统负载
node_load1
node_load5
node_load15

# 网络流量
irate(node_network_receive_bytes_total[5m])
irate(node_network_transmit_bytes_total[5m])
```

## 故障排查

### 服务无法启动

```bash
# 检查服务状态
systemctl status node_exporter

# 查看详细日志
journalctl -u node_exporter -n 50 --no-pager

# 检查端口占用
ss -tulnp | grep 9100

# 检查二进制文件权限
ls -la /usr/local/node_exporter/
```

### 指标未出现在 VictoriaMetrics

1. **检查 node_exporter 是否运行**
   ```bash
   curl http://localhost:9100/metrics | head
   ```

2. **检查 VictoriaMetrics 抓取配置**
   ```bash
   # 在 gtr 服务器上
   cat /usr/local/victoriametrics/victoriametrics_sd.yaml
   ```

3. **查看 VictoriaMetrics 日志**
   ```bash
   journalctl -u victoriametrics -f | grep -i scrape
   ```

4. **测试 VictoriaMetrics 能否访问目标**
   ```bash
   curl http://localhost:9100/metrics
   ```

### 端口被占用

```bash
# 查找占用端口的进程
sudo lsof -i :9100
# 或
sudo ss -tulnp | grep 9100

# 终止占用端口的进程
sudo kill <PID>
```

## 高级配置

### 启用额外收集器

编辑 systemd 服务文件：

```bash
sudo nano /etc/systemd/system/node_exporter.service
```

添加 `--collector.*` 参数，例如：

```ini
ExecStart=/usr/local/node_exporter/node_exporter \
    --web.listen-address=:9100 \
    --collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/) \
    --collector.textfile.directory=/var/lib/node_exporter \
    --collector.ntp
```

重载配置：

```bash
sudo systemctl daemon-reload
sudo systemctl restart node_exporter
```

### 使用 textfile 收集器添加自定义指标

```bash
# 创建目录
sudo mkdir -p /var/lib/node_exporter
sudo chown node_exporter:node_exporter /var/lib/node_exporter

# 添加自定义指标
echo 'my_custom_metric{label="value"} 42' | sudo tee /var/lib/node_exporter/my_metrics.prom
sudo chown node_exporter:node_exporter /var/lib/node_exporter/my_metrics.prom
```

## 卸载

```bash
# 停止并禁用服务
sudo systemctl stop node_exporter
sudo systemctl disable node_exporter

# 删除服务文件
sudo rm /etc/systemd/system/node_exporter.service
sudo systemctl daemon-reload

# 删除用户和组
sudo userdel node_exporter
sudo groupdel node_exporter

# 删除二进制文件
sudo rm -rf /usr/local/node_exporter

# 删除防火墙规则（如已配置）
sudo ufw delete allow 9100/tcp
```

## 升级

```bash
# 下载新版本的部署脚本或修改版本号
export NODE_EXPORTER_VERSION="1.9.0"

# 备份当前配置
sudo cp /etc/systemd/system/node_exporter.service /tmp/node_exporter.service.bak

# 运行安装脚本
./install.sh
```

## 监控建议

### 在 Grafana 中创建仪表板

推荐的 Grafana 仪表板模板：
- **Node Exporter Full** (ID: 1860)
- **Node Exporter for Prometheus** (ID: 11074)

导入方法：
1. 登录 Grafana (http://gtr:3000)
2. 导航到 Dashboards → Import
3. 输入仪表板 ID 或上传 JSON 文件
4. 选择 VictoriaMetrics 数据源

### 关键告警规则建议

```promql
# CPU 使用率过高 (80%)
100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80

# 内存使用率过高 (90%)
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90

# 磁盘空间不足 (10%)
(node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100 < 10

# 系统负载过高
node_load15 > (count by(instance) (node_cpu_seconds_total{mode="idle"}) * 0.8)

# 节点宕机
up{job="node_exporter"} == 0
```
