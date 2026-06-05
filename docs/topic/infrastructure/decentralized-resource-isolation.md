## 去中心化资源隔离方案

### 设计原则

1. **各层自治** — 基础设施（gtr-services）和应用（gtr-release-config）各自声明资源占用，不互相提交 PR
2. **契约文件** — 双方各产出一份标准格式的 manifest（YAML），提交到各自仓库
3. **部署时仲裁** — deployctl 部署前 SSH 读取 GTR 上的基础设施 manifest，与本地应用 manifest 交叉验证
4. **CI 前置** — PR 阶段即可检测冲突，不必等到部署时才发现

### 架构

```
┌─────────────────────────────┐      ┌──────────────────────────────┐
│  gtr-services (基础设施)      │      │  gtr-release-config (应用)    │
│                             │      │                              │
│  .resource-manifest.yml     │      │  .resource-manifest.yml      │
│    ports: [80, 443, 3000…]  │      │    ports: [8190]             │
│    subuid: [100000…]        │      │    subuid: [262144]          │
│    users: []                │      │    users: [svc-cfm]          │
│                             │      │                              │
│  scripts/gen-manifest.sh    │      │  scripts/gen-manifest.sh     │
│    ↓ 生成 + 提交到仓库       │      │    ↓ 生成 + 提交到仓库        │
└─────────────┬───────────────┘      └──────────────┬───────────────┘
              │                                     │
              │ commit manifest                     │ CI: validate → deploy
              │                                     │
              ▼                                     ▼
         ┌──────────────────────────────────────────────┐
         │                GTR 主机                       │
         │                                              │
         │  /etc/gtr/resource-manifest.infra.yml        │
         │    ← Ansible 部署时写入                       │
         │                                              │
         │  deployctl 部署前:                            │
         │    1. SSH cat /etc/gtr/resource-manifest.infra.yml
         │    2. 与本地 .resource-manifest.yml 交叉验证   │
         │    3. 无冲突 → 继续部署                       │
         │    4. 有冲突 → 拒绝部署 + 报告冲突项           │
         └──────────────────────────────────────────────┘
```

### 资源 Manifest 格式

双方使用相同格式，放在仓库根目录的 `.resource-manifest.yml`：

```yaml
# .resource-manifest.yml
# 声明本层占用的共享资源，由 gen-manifest.sh 生成或手动维护
schema_version: 1
layer: infrastructure  # infrastructure | application
generated_at: "2026-06-02T12:00:00Z"

subuid:
  - user: lynskylate
    start: 100000
    size: 65536

ports:
  - port: 80
    protocol: tcp
    service: envoy
  - port: 443
    protocol: tcp
    service: envoy-tls
  - port: 3000
    protocol: tcp
    service: grafana
  # ...

users: []  # 基础设施层不创建应用服务用户

nftables_chains:
  - ts-forward
  - ts-input
  - ts-postrouting
```

### 冲突检测规则

| 资源类型 | 冲突条件 |
|----------|----------|
| **subuid** | 两层的 [start, start+size) 范围有交集 |
| **ports** | 同一 protocol + port 被两层同时声明 |
| **users** | 同一 username 被两层同时声明 |
| **nftables_chains** | 应用层不应声明任何 nftables chain（reserved for infra） |

### 生命周期

**基础设施侧（gtr-services）：**

1. 开发者修改 Ansible 配置（新增端口、修改 subuid 等）
2. `scripts/gen-manifest.sh` 从 `group_vars/` 提取资源声明，生成 `.resource-manifest.yml`
3. 提交到 git，PR review 时 CI 检查格式合法性
4. merge 后 Ansible 部署时同步写入 `/etc/gtr/resource-manifest.infra.yml`

**应用侧（gtr-release-config）：**

1. 开发者新增/修改应用服务（新端口、新用户等）
2. 更新 `.resource-manifest.yml`（手动或通过 gen-manifest.sh）
3. PR 阶段 CI 运行 `validate-contract.sh`，从缓存或 artifact 读取基础设施 manifest 做交叉检查
4. merge 后 deployctl 部署前再次实时验证（SSH 读 GTR 上的基础设施 manifest）

**冲突发现后：**

- CI 报错指出具体冲突项（如 "port 8190 already claimed by infrastructure layer"）
- 开发者自行调整（换一个端口 / 与基础设施 owner 沟通）
- 不需要向对方仓库提 PR

### 与旧方案的对比

| 维度 | 旧方案（集中注册表） | 新方案（去中心化契约） |
|------|---------------------|----------------------|
| 新增应用端口 | 需修改 gtr-services group_vars | 只改 gtr-release-config 自己的 manifest |
| 新增服务用户 | 需注册到 gtr-services | deployctl 创建，manifest 声明即可 |
| 冲突检测时机 | Ansible verify 时（部署后） | CI PR 阶段 + deployctl 部署前（部署前） |
| 跨仓库协调 | 需要（应用改基础设施代码） | 不需要（各自声明，自动仲裁） |
| 回滚影响 | 两层耦合 | 各层独立回滚 |
