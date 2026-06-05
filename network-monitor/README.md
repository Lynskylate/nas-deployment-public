# 网络连通性监控（Mihomo 代理分流规则验证）

网络连通性监控解决方案，**通过 Mihomo 代理测试国内外网站的连通性，以验证 Mihomo 的自动分流规则是否正常工作**。

通过 Vector 收集结构化日志并发送到 VictoriaLogs，最后在 Grafana 中进行可视化展示。

## 监控原理

所有网站的访问都通过 **Mihomo 代理 (127.0.0.1:7890)**，这样可以测试 Mihomo 的分流规则：

- **国内网站** - 应该被 Mihomo 直连（快速响应）
- **国外网站** - 应该被 Mihomo 转发到上游代理（正常响应）

## 架构概览

```
Network Monitor Script (Cron)
    │
    └─→ 所有网站通过 Mihomo 代理 (127.0.0.1:7890)
        │
        ├─→ 国内网站 (expected_route: direct)
        │   └─→ 小米、百度、支付宝
        │       └─→ 验证: 响应时间应该较快（直连）
        │
        └─→ 国外网站 (expected_route: proxy)
            └─→ Google、Cloudflare、GitHub、YouTube
                └─→ 验证: 响应正常（转发）

    ↓ (JSON 日志)

Vector (日志收集)
    ↓ (解析和转换)

VictoriaLogs (存储)
    ↓ (LogsQL 查询)

Grafana (可视化)
```

## 监控网站列表

### 国内网站（通过 Mihomo，expected_route: direct）
- `xiaomi` - http://connect.rom.miui.com/generate_204
- `baidu` - http://www.baidu.com
- `alipay` - https://www.alipay.com

### 国外网站（通过 Mihomo，expected_route: proxy）
- `google` - http://www.google.com/generate_204
- `cloudflare` - http://www.cloudflare.com/cdn-cgi/trace
- `github` - https://api.github.com
- `youtube` - https://www.youtube.com/generate_204

## 文件说明

```
network-monitor/
├── network-monitor.sh           # 监控脚本主程序
├── network-monitor-wrapper.sh   # 包装脚本（用于 cron）
├── vector.toml                  # Vector 配置文件
├── deploy.sh                    # 部署脚本
├── ansible/
│   ├── inventory.ini            # Ansible 主机清单
│   └── deploy.yml               # Ansible 部署剧本
└── README.md                    # 本文件
```

## 快速开始

### 前置条件

1. gtr 服务器上已安装 Vector 并配置 VictoriaLogs
2. Mihomo 代理运行在 127.0.0.1:7890
3. 本地已安装 Ansible

```bash
# 安装 Ansible
sudo apt install ansible
```

### 部署步骤

```bash
# 进入目录
cd network-monitor

# 1. 本地测试脚本
./deploy.sh local

# 2. 部署到 gtr 服务器
./deploy.sh deploy

# 3. 验证部署
./deploy.sh verify

# 4. 查看日志
./deploy.sh logs
```

## 手动测试

```bash
# 本地测试
./network-monitor.sh direct    # 仅测试国内网站
./network-monitor.sh proxy     # 仅测试国外网站
./network-monitor.sh all       # 测试所有网站

# 在 gtr 服务器上测试
ssh gtr
/usr/local/network-monitor/network-monitor.sh all
```

## 日志格式

每条日志记录包含以下字段：

```json
{
  "timestamp": "2026-02-11T12:00:00Z",
  "site": "google",
  "url": "http://www.google.com/generate_204",
  "status_code": 200,
  "response_time": 0.234,
  "proxy": true,
  "test_type": "international"
}
```

| 字段 | 说明 |
|------|------|
| `timestamp` | ISO 8601 格式时间戳 |
| `site` | 网站标识符 |
| `url` | 完整 URL |
| `status_code` | HTTP 状态码（200/204=成功，000=失败） |
| `response_time` | 响应时间（秒） |
| `proxy` | 代理类型（固定为 "mihomo"） |
| `expected_route` | 预期路由：direct（国内直连）或 proxy（国外转发） |
| `route_type` | 路由类型：domestic 或 international |

## Grafana 配置

### 数据源设置

VictoriaLogs 数据源应已配置：
- URL: `http://localhost:8429`
- 类型: VictoriaLogs

### LogsQL 查询示例

#### 1. 国内网站连通性状态（通过 Mihomo，应该直连）

```logsql
container_name:network-monitor expected_route:direct
| line_format "{{.site}}: {{.status_code}}"
| keep status_code, site
```

#### 2. 国外网站连通性状态（通过 Mihomo，应该转发）

```logsql
container_name:network-monitor expected_route:proxy
| line_format "{{.site}}: {{.status_code}}"
| keep status_code, site
```

#### 3. 国内网站最新状态码

```logsql
container_name:network-monitor expected_route:direct site:xiaomi
| line_format "{{.status_code}}"
| keep status_code
```

#### 4. 国外网站最新状态码

```logsql
container_name:network-monitor expected_route:proxy site:google
| line_format "{{.status_code}}"
| keep status_code
```

#### 5. 国内网站响应时间趋势（验证 Mihomo 直连路由）

```logsql
container_name:network-monitor expected_route:direct status_code:[200 TO 299]
| line_format "{{.response_time}}"
| keep response_time
```

#### 6. 国外网站响应时间趋势

```logsql
container_name:network-monitor expected_route:proxy status_code:[200 TO 299]
| line_format "{{.response_time}}"
| keep response_time
```

#### 7. 比较国内外网站响应时间（验证分流规则）

```logsql
container_name:network-monitor status_code:[200 TO 299]
| line_format "{{.route_type}}: {{.response_time}}"
| keep response_time, route_type
```

### 面板配置建议

#### 连通性状态面板（Stat）

1. **国内网站状态（通过 Mihomo 直连）**
   - 查询: `container_name:network-monitor expected_route:direct site:xiaomi | line_format "{{.status_code}}" | keep status_code`
   - 阈值设置:
     - 200 或 204 → 绿色（正常）
     - 000 → 黄色（连接失败）
     - 其他 → 红色（错误）

2. **国外网站状态（通过 Mihomo 转发）**
   - 查询: `container_name:network-monitor expected_route:proxy site:google | line_format "{{.status_code}}" | keep status_code`
   - 阈值设置:
     - 200 或 204 → 绿色（正常）
     - 000 → 黄色（连接失败）
     - 其他 → 红色（错误）

#### 响应时间面板（Time Series）

1. **国内网站响应时间（验证直连路由，应该较快）**
   - 查询: 使用上面查询 5
   - 可视化: Time series
   - 说明: 如果响应时间突然变高，可能 Mihomo 分流规则有问题

2. **国外网站响应时间**
   - 查询: 使用上面查询 6
   - 可视化: Time series

3. **国内外网站响应时间对比**
   - 查询: 使用上面查询 7
   - 可视化: Time series (by route_type)
   - 说明: 可以直观看到国内（直连）和国外（转发）的响应时间差异

#### 表格面板（Table）

显示所有网站的最新状态：

```logsql
container_name:network-monitor
| line_format "{{.timestamp}} | {{.site}} | {{.expected_route}} | {{.status_code}} | {{.response_time}}s"
| keep message
```

### 阈值配置示例

在 Grafana 面板中配置阈值：

1. 打开 Field 设置
2. 设置 Thresholds：
   - `200` 为绿色（表示成功）
   - `000` 为黄色（表示连接失败）
   - 其他状态码（如 `500`, `404`）为红色（表示错误）

## 维护操作

### 查看服务状态

```bash
# SSH 到 gtr 服务器
ssh gtr

# 查看 cron 任务
crontab -l | grep network-monitor

# 查看 Vector 状态
systemctl status vector

# 查看实时日志
tail -f /var/log/network-monitor/network-monitor.log
```

### 调整监控频率

编辑 Ansible 变量 `monitor_interval`（默认 1 分钟）：

```yaml
vars:
  monitor_interval: 5  # 改为每 5 分钟
```

然后重新部署：

```bash
./deploy.sh deploy
```

### 添加新的监控网站

编辑 `network-monitor.sh`，在 `test_site` 调用部分添加新网站：

```bash
# 国内网站
test_site "new-site" "http://example.com" "false"

# 国外网站
test_site "new-foreign-site" "http://foreign-site.com" "true"
```

### 日志轮转

日志默认保留 7 天，每天轮转一次。配置文件：`/etc/logrotate.d/network-monitor`

### 卸载

```bash
./deploy.sh uninstall
```

## 故障排查

### 问题：没有日志输出

```bash
# 检查 cron 是否运行
systemctl status cron

# 手动运行脚本
/usr/local/network-monitor/network-monitor-wrapper.sh

# 检查日志文件权限
ls -la /var/log/network-monitor/
```

### 问题：国外网站全部失败

```bash
# 检查 Mihomo 代理状态
systemctl status mihomo
ss -tulnp | grep 7890

# 测试代理连接
curl -x 127.0.0.1:7890 http://www.google.com/generate_204
```

### 问题：Vector 无法收集日志

```bash
# 检查 Vector 配置
vector validate --config /etc/vector/vector.toml

# 查看 Vector 日志
journalctl -u vector -f

# 检查日志文件权限
ls -la /var/log/network-monitor/network-monitor.log
```

## 参考资料

- [参考文章](https://deeprouter.org/article/grafana-home-network-internal-external-connectivity-monitoring)
- [VictoriaLogs 文档](https://docs.victoriametrics.com/victorialogs/)
- [Vector 文档](https://vector.dev/docs/)
- [LogsQL 查询语言](https://docs.victoriametrics.com/victorialogs/logsql/)
