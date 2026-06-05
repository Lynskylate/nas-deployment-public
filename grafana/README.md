# Grafana Service - Runbook

## 服务概述

Grafana 是一个开源的可视化和监控平台，用于创建仪表板、图表和警报。

## 服务信息

| 项目 | 值 |
|------|-----|
| 服务名称 | grafana |
| 运行用户 | grafana |
| HTTP 端口 | 3000 |
| 安装目录 | /usr/local/grafana |
| 数据目录 | /usr/local/grafana/data |
| 数据库类型 | SQLite3 |

## 配置文件

| 文件路径 | 说明 |
|---------|------|
| /etc/systemd/system/grafana.service | Systemd 服务单元文件 |
| /usr/local/grafana/conf/defaults.ini | 默认配置文件 |
| /usr/local/grafana/conf/ldap.toml | LDAP 配置 |
| /usr/local/grafana/conf/provisioning/ | 自动配置目录 |

## 服务管理

```bash
# 连接到服务器
ssh gtr

# 查看服务状态
systemctl status grafana

# 启动服务
sudo systemctl start grafana

# 停止服务
sudo systemctl stop grafana

# 重启服务
sudo systemctl restart grafana

# 查看服务日志
journalctl -u grafana -f

# 查看最近100行日志
journalctl -u grafana -n 100

# 查看 Grafana 自己的日志
tail -f /usr/local/grafana/data/log/grafana.log
```

## Web 访问

- **Grafana UI**: http://gtr:3000

## 数据源配置

当前配置的数据源：

1. **VictoriaMetrics** - 时序指标数据
   - 地址: http://localhost:8428

2. **VictoriaLogs** - 日志数据
   - 地址: http://localhost:8429
   - 插件: victoriametrics-logs-datasource

## 插件

已安装的插件：
- victoriametrics-logs-datasource - VictoriaLogs 数据源插件

插件目录：`/usr/local/grafana/data/plugins/`

## 用户管理

### 默认管理员

- 默认用户名: `admin`
- 首次登录需设置密码

### LDAP 配置

Grafana 配置了 LDAP 认证：
- 主配置: `/usr/local/grafana/conf/ldap.toml`
- 多配置: `/usr/local/grafana/conf/ldap_multiple.toml`

## 仪表板 (Dashboards)

仪表板存储位置：`/usr/local/grafana/data/dashboards/`

仓库内的 OpenClaw 简要日志仪表板模板：
- `grafana/openclaw-victorialogs-dashboard.json`（VictoriaLogs 数据源，UID: `cfcy98m8h4zy8f`）

### 导出仪表板

1. 打开仪表板
2. 点击 Share -> Export
3. 选择 "Save to file"

### 导入仪表板

1. 点击 "+" -> "Import"
2. 上传 JSON 文件或粘贴内容
3. 选择数据源
4. 点击 Import

## Provisioning (自动配置)

Grafana 支持通过 provisioning 目录自动配置数据源和仪表板：

```
/usr/local/grafana/conf/provisioning/
├── datasources/     # 数据源自动配置
├── dashboards/      # 仪表板自动配置
└── plugins/         # 插件配置
```

当前仓库已固化 Dashboard Provider：
- Provider 配置：`grafana/provisioning/dashboards/local-provisioned.yaml`
- Dashboard JSON 目录：`grafana/dashboards/`
- 应用方式：按需将以上文件同步到 gtr 的 Grafana provisioning 目录

## 常见操作

### 重置管理员密码

```bash
# 使用 Grafana CLI 重置为 admin/admin
cd /usr/local/grafana
sudo ./bin/grafana-cli admin reset-admin-password

# 或在配置文件中设置 [security] admin_user 和 admin_password
```

### 添加新数据源

1. 登录 Grafana
2. Configuration -> Data Sources -> Add data source
3. 选择数据源类型
4. 配置连接信息
5. 点击 Save & Test

## 故障排查

### 服务无法启动

```bash
# 检查服务状态
systemctl status grafana

# 查看详细日志
journalctl -u grafana -n 100 --no-pager

# 检查端口占用
ss -tulnp | grep 3000

# 检查数据目录权限
ls -la /usr/local/grafana/data/
```

### 数据源连接失败

```bash
# 测试 VictoriaMetrics 连接
curl http://localhost:8428/health

# 测试 VictoriaLogs 连接
curl http://localhost:8429/health

# 检查防火墙规则
sudo iptables -L -n | grep 3000
```

## 备份与恢复

### 备份

```bash
# 备份 Grafana 数据目录
sudo tar -czf grafana-backup-$(date +%Y%m%d).tar.gz /usr/local/grafana/data

# 备份数据库（SQLite）
sudo cp /usr/local/grafana/data/grafana.db grafana.db.backup
```

### 恢复

```bash
# 停止服务
sudo systemctl stop grafana

# 恢复数据目录
sudo tar -xzf grafana-backup-YYYYMMDD.tar.gz -C /

# 启动服务
sudo systemctl start grafana
```

## 配置说明

### Server 配置

| 配置项 | 值 | 说明 |
|-------|-----|------|
| protocol | http | 协议 |
| http_port | 3000 | HTTP 端口 |
| domain | localhost | 域名 |

### Database 配置

| 配置项 | 值 | 说明 |
|-------|-----|------|
| type | sqlite3 | 数据库类型 |
| path | grafana.db | 数据库文件路径 |

## 升级 Grafana

```bash
# 下载新版本
wget https://dl.grafana.com/oss/release/grafana-<version>.linux-amd64.tar.gz

# 停止服务
sudo systemctl stop grafana

# 备份数据
sudo cp -r /usr/local/grafana/data /usr/local/grafana/data.backup

# 解压新版本
sudo tar -xzf grafana-<version>.linux-amd64.tar.gz -C /usr/local/

# 启动服务
sudo systemctl start grafana
```
