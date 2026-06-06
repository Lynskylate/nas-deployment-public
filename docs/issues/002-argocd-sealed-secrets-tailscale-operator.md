# [Migration] Install Argo CD, Sealed Secrets, And Tailscale Operator

## Summary

Bootstrap the K3s platform control plane in a single execution flow:

1. **Argo CD** — GitOps reconciler (installed via Ansible, bootstraps itself)
2. **Sealed Secrets** — Runtime secret delivery (installed via Ansible, managed by Argo CD after)
3. **Tailscale Operator** — Tailnet-native ingress for K3s services (deployed as Argo CD Application)

After this migration, application repositories can self-manage their Helm charts and Kubernetes resources through Argo CD, with secrets encrypted in Git via Sealed Secrets and services exposed over Tailscale via the Operator.

## Architecture Decisions (Confirmed)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Service exposure** | Tailscale Operator (not Envoy<->K3s bridge) | MagicDNS 直接访问，无需维护额外入口层 |
| **Exposure scope** | Tailnet 成员（不启用 Funnel） | 无需公网暴露，ACL 控制访问 |
| **Secret management** | Sealed Secrets | 加密 Secret 可安全提交到公开仓库 |
| **GitOps** | Argo CD + App-of-Apps | 平台和应用统一管理入口 |
| **Platform repo** | `nas-deployment-public`（不新建 repo） | 部署原子性，CI 权限统一 |
| **Argo CD bootstrap** | Ansible 驱动（`k3s kubectl` 在 aliyun 执行） | 复用现有部署基础设施 |

## Pre-Requisites

### 1. Tailscale Admin Console 配置（需手动完成一次）

#### ✅ OAuth Client（已创建）

在 https://login.tailscale.com/admin/settings/oauth：

| 字段 | 值 |
|------|-----|
| **Description** | `k3s-tailscale-operator` |
| **Scopes** | `devices`（最小权限） |
| **Tag** | `tag:k8s-operator` |

```
Client ID:     <REDACTED - see nas-deployment-vault>
Client Secret: <REDACTED - see nas-deployment-vault>
```

> `devices` scope 允许 Operator 的 proxy Pod 注册为 Tailscale 节点。
> 已验证：token 获取 ✅，auth key 创建 ❌（不需要），设备列表读取 ❌（不需要）。
> 权限符合最小原则。

凭据已加密存入 `nas-deployment-vault/infra/tailscale-operator/oauth.sops.yml`。

#### 📋 ACL Grants（需手动补全）

在你的现有配置基础上，新增以下三处：

```json
{
    // 1. grants — 允许 tailnet 成员访问 proxy Pod 暴露的服务
    "grants": [
        // ... 你已有的 grants ...
        {
            "src": ["autogroup:member"],
            "dst": ["tag:k8s-proxy"],
            "ip":  ["443"]
        },
        {
            "src": ["tag:k8s-operator"],
            "dst": ["tag:k8s-proxy"],
            "ip":  ["*"]
        },
    ],

    // 2. tagOwners — 允许 operator 创建 proxy 节点
    "tagOwners": {
        // ... 你已有的 tagOwners ...
        "tag:k8s-operator": ["autogroup:admin"],
        "tag:k8s-proxy":    ["tag:k8s-operator"],
    },

    // 3. autoApprovers — 自动审批 service host
    "autoApprovers": {
        "services": {
            // ... 你已有的 ...
            "svc:*": ["tag:k8s-operator"]
        },
    },
}
```

**配置总结：**
- OAuth 只需要 `devices` scope（不需要 `auth_keys` 或 `api_key`）
- `tag:k8s-operator` 是 Operator 身份 tag，`tag:k8s-proxy` 是 proxy Pod 默认 tag
- `tagOwners` 中 `tag:k8s-proxy` 必须由 `tag:k8s-operator` 拥有，否则 Operator 无法创建 proxy 节点

### 2. 访问凭据

| 凭据 | 来源 | 用途 |
|------|------|------|
| `argocd_admin_password` | Argo CD 安装后自动生成 | Argo CD Web UI/CLI 登录 |
| `argocd_repo_ssh_key` | GitHub Deploy Key | Argo CD 拉取应用仓库 |
| `tailscale_operator_oauth_client_id` | Tailscale Admin Console | ✅ `kN2Q6wMy1Y11CNTRL`（已存入 vault） |
| `tailscale_operator_oauth_client_secret` | Tailscale Admin Console | ✅ 已存入 vault |
| `sealed_secrets_private_key_backup` | 安装时从集群导出 | 灾难恢复 |

以上凭据在 CI 部署时从 `nas-deployment-vault`（sops+age 加密）解密，写入对应 K8s Secret 或 Ansible vars。

## Execution Plan

### Phase 0: Directory & Role Scaffolding

新增平台组件目录结构和 Ansible 角色骨架。

```
nas-deployment-public/
├── edge/ansible/                    ← 现有
│   ├── roles/
│   │   └── argocd/                  ← 📋 新增：Argo CD 安装角色
│   │       ├── tasks/main.yml
│   │       ├── templates/
│   │       │   └── argocd-repo-secret.yaml.j2      ← Argo CD repo 凭证模板
│   │       ├── defaults/main.yml
│   │       └── handlers/main.yml
│   ├── deploy-platform-argocd.yml              ← 📋 新增
│   ├── deploy-platform-sealed-secrets.yml      ← 📋 新增
│   ├── verify-platform-argocd.yml              ← 📋 新增
│   ├── verify-platform-sealed-secrets.yml      ← 📋 新增
│   └── verify-platform-tailscale-operator.yml  ← 📋 新增
│
├── platform/                          ← 📋 新增：K3s 内平台组件声明式配置
│   ├── README.md                      ← 目录概览
│   │
│   ├── applications/                  ← Argo CD Application CRDs（App-of-Apps）
│   │   ├── kustomization.yaml
│   │   ├── sealed-secrets.yaml
│   │   └── tailscale-operator.yaml
│   │
│   ├── argocd/                        ← Argo CD 安装参考（install.yaml 副本）
│   │
│   ├── sealed-secrets/                ← Sealed Secrets 安装参考
│   │
│   └── helm-values/
│       └── tailscale-operator/
│           └── values.yaml            ← Operator Helm values override
│
└── .github/workflows/
    └── deploy-infra.yml               ← 新增 deploy-platform-operators job
```

### Phase 1: Bootstrap Argo CD

**驱动方式：** Ansible playbook `deploy-platform-argocd.yml`，目标主机 `edge_aliyun`（K3s server 节点，kubectl 就绪）。

#### 安装步骤

```
1. 创建 namespace argocd
2. 下载 Argo CD install.yaml 并 apply
3. 等待 argocd-server/argocd-dex-server/argocd-redis Pod 就绪
4. 获取初始 admin 密码（从 argocd-initial-admin-secret）
5. 创建 repo 凭证 Secret（从 vault 解密后的 SSH key）
6. 通过 Argo CD CLI 添加 cluster（当前集群 self）
7. 创建 App-of-Apps Application（指向本 repo platform/applications/）
```

> Argo CD UI 初期不暴露到 tailnet。Tailscale Operator 安装后，通过注解 argocd-server Service（`tailscale.com/expose: "true"`）自动获得 MagicDNS 域名。
> 在此之前，管理员通过 `k3s kubectl port-forward -n argocd svc/argocd-server 8080:80` 临时访问。

#### Ansible 角色 `roles/argocd/`

```yaml
# tasks/main.yml 核心逻辑
- name: Create argocd namespace
  ansible.builtin.command: k3s kubectl create namespace argocd --dry-run=client -o yaml | k3s kubectl apply -f -
  changed_when: false

- name: Apply Argo CD install manifests
  ansible.builtin.shell: |
    k3s kubectl apply -n argocd -f {{ argocd_install_manifest_url }}
  changed_when: false

- name: Wait for Argo CD rollout
  ansible.builtin.shell: |
    k3s kubectl -n argocd rollout status deployment/argocd-server --timeout=120s

- name: Get initial admin password
  ansible.builtin.shell: |
    k3s kubectl -n argocd get secret argocd-initial-admin-secret \
      -o jsonpath='{.data.password}' | base64 -d
  register: argocd_admin_password
  changed_when: false

- name: Create repo credential secret from vault
  ansible.builtin.template:
    src: argocd-repo-secret.yaml.j2
    dest: /tmp/argocd-repo-secret.yaml
  changed_when: false

- name: Apply repo credential secret
  ansible.builtin.shell: |
    k3s kubectl apply -n argocd -f /tmp/argocd-repo-secret.yaml
    rm -f /tmp/argocd-repo-secret.yaml
  changed_when: false

- name: Create App-of-Apps Application
  ansible.builtin.shell: |
    k3s kubectl apply -n argocd -f /path/to/platform/applications/kustomization.yaml
  changed_when: false
```

#### 验证

```bash
# 在 aliyun 上通过 kubectl 验证
k3s kubectl -n argocd get pods
# 期望: argocd-server/argocd-redis/argocd-dex-server Running

# port-forward 后验证 UI 可达
k3s kubectl port-forward -n argocd svc/argocd-server 8080:80 &
curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:8080
# 期望: 200

# Argo CD CLI 登录验证（通过 port-forward）
argocd login localhost:8080 --username admin --password <initial-password> --grpc-web
argocd cluster list
# 期望: 显示当前集群 (self)
```

### Phase 2: Bootstrap Sealed Secrets

**驱动方式：** Ansible playbook `deploy-platform-sealed-secrets.yml`，目标主机 `edge_aliyun`。

#### 安装步骤

```
1. 下载 Sealed Secrets controller manifests 并 apply
2. 等待 sealed-secrets-controller Pod 就绪
3. 导出 controller 公钥（用于本地 kubeseal）
4. 导出 controller 私钥备份（sops 加密后存入 vault repo）
5. 创建 Argo CD Application CRD（sealed-secrets.yaml），后续由 Argo CD 管理
6. 运行验证：加密一个测试 Secret → apply SealedSecret → 确认自动解密
```

#### 安装方式选择

| 方案 | 优势 | 劣势 |
|------|------|------|
| **kubectl apply**（推荐） | 简单，与 Argo CD 安装方式一致 | 非 Helm 管理 |
| **Helm chart** | 可定制 values | 需要先装 Helm |

**选择 kubectl apply**（bitnami-labs/sealed-secrets 官方推荐方式）。

```bash
k3s kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.27.2/controller.yaml
```

#### 私钥备份策略

```bash
# 导出私钥（安装后立即执行）
k3s kubectl get secret -n kube-system \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o yaml > sealed-secrets-key-backup.yaml

# sops 加密后存入 vault repo
sops --encrypt --age <AGE_KEY> sealed-secrets-key-backup.yaml \
  > nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml

# 删除本地明文
rm sealed-secrets-key-backup.yaml
```

#### 验证

```bash
# 从 CI 或开发者本地
kubeseal --controller-namespace=kube-system \
         --fetch-cert > public-key.pem

echo -n "hello-world" | kubectl create secret generic test-secret \
  --dry-run=client -o json --from-file=/dev/stdin \
  | kubeseal --cert=public-key.pem --format=yaml \
  > platform/sealed-secrets/test-sealed.yaml

k3s kubectl apply -f platform/sealed-secrets/test-sealed.yaml
k3s kubectl get secret test-secret -o jsonpath='{.data.dev-stdin}'
# 期望：base64 编码的 "hello-world"
```

### Phase 3: Deploy Tailscale Operator

**驱动方式：** 通过 Argo CD Application CRD 管理（GitOps 模式）。

Argo CD 就绪后，`platform/applications/tailscale-operator.yaml` 会被 App-of-Apps 自动同步。

#### 前置条件

- [x] Tailscale OAuth Client 已创建（Pre-Requisites）
- [x] Client ID + Secret 已加密存入 `nas-deployment-vault/infra/tailscale-operator/oauth.sops.yml`
- [ ] Argo CD 已在集群中运行（Phase 1 完成）

#### 安装步骤

```
1. 将 OAuth 凭据创建为 SealedSecret（owner: platform team）
   → platform/tailscale-operator/secrets/
2. 创建 Argo CD Application CRD
   → platform/applications/tailscale-operator.yaml
3. App-of-Apps 自动发现并同步
4. 验证 Operator Pod 正常运行
5. 将 argocd-server Service 加上 tailscale.com/expose 注解 → 自动获得 MagicDNS 域名
6. 部署测试 workload，通过 MagicDNS 访问验证
```

#### Argo CD Application CRD

```yaml
# platform/applications/tailscale-operator.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tailscale-operator
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://tailscale.github.io/charts
    chart: tailscale-operator
    targetRevision: "1.x"         # [VERIFY] 最新版本
    helm:
      values: |
        operator:
          oauth:
            clientId: "{{ 从 SealedSecret 引用 }}"
            clientSecret: "{{ 从 SealedSecret 引用 }}"
          tags: "tag:k8s-proxy"
          hostname: "k3s"
  destination:
    server: https://kubernetes.default.svc
    namespace: tailscale
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

#### 暴露 Argo CD UI（Operator 就绪后）

Tailscale Operator 安装完成后，给 argocd-server Service 加注解，自动获得 MagicDNS 域名：

```bash
k3s kubectl annotate service argocd-server \
  -n argocd tailscale.com/expose=true
# 等待 Proxy Pod 创建
k3s kubectl -n tailscale get pods -w | grep argocd
# 访问: https://argocd-server-argocd.tail414c32.ts.net
```

#### 验证

```bash
# 检查 Operator Pod
k3s kubectl -n tailscale get pods

# 部署测试 Service（带 tailscale.com/expose 注解）
k3s kubectl create deployment nginx-test --image=nginx
k3s kubectl expose deployment nginx-test --port=80 \
  --type=ClusterIP --name=nginx-test
k3s kubectl annotate service nginx-test \
  tailscale.com/expose=true

# 等待 Proxy Pod 就绪
k3s kubectl -n tailscale get pods -w

# 从 tailnet 设备访问
curl https://nginx-test-default.tail414c32.ts.net
# 期望：nginx 欢迎页面

# Argo CD 也已在 tailnet 上
curl -sf -o /dev/null -w "%{http_code}" \
  https://argocd-server-argocd.tail414c32.ts.net
# 期望: 200
```

### Phase 4: CI 集成

在 `.github/workflows/deploy-infra.yml` 中新增 job：

```yaml
deploy-platform-operators:
  needs: [preflight, deploy-k3s-agent]
  if: needs.preflight.outputs.run_k3s_agent == 'true'
  runs-on: ubuntu-latest
  timeout-minutes: 20
  environment: production
  steps:
    # ... (checkout, bootstrap, tailscale 连接同其他 job)
    
    - name: Deploy Argo CD
      working-directory: edge/ansible
      run: ansible-playbook -i inventory-edge.ini deploy-platform-argocd.yml -v
    
    - name: Verify Argo CD
      working-directory: edge/ansible
      run: ansible-playbook -i inventory-edge.ini verify-platform-argocd.yml -v
    
    - name: Deploy Sealed Secrets
      working-directory: edge/ansible
      run: ansible-playbook -i inventory-edge.ini deploy-platform-sealed-secrets.yml -v
    
    - name: Verify Sealed Secrets
      working-directory: edge/ansible
      run: ansible-playbook -i inventory-edge.ini verify-platform-sealed-secrets.yml -v
    
    - name: Back up Sealed Secrets private key to vault
      run: |
        ssh root@gtr.tail414c32.ts.net << 'BACKUP'
          k3s kubectl get secret -n kube-system \
            -l sealedsecrets.bitnami.com/sealed-secrets-key \
            -o yaml > /tmp/sealed-secrets-key-backup.yaml
        BACKUP
        scp root@gtr.tail414c32.ts.net:/tmp/sealed-secrets-key-backup.yaml /tmp/
        # sops encrypt and push to vault repo
        ...
    
    - name: Verify Tailscale Operator sync status
      working-directory: edge/ansible
      run: ansible-playbook -i inventory-edge.ini verify-platform-tailscale-operator.yml -v

    - name: Verify end-to-end (test workload on tailnet)
      run: |
        # 部署 nginx-test，验证 MagicDNS 可达
        ...
```

**CI 依赖链（更新后）：**

```
preflight
  ├→ deploy-gtr
  │    ├→ deploy-edge (aliyun/tencent/remote_proxy)
  │    └→ deploy-k3s-server (aliyun) ← 与 deploy-edge 并行
  │         └→ deploy-k3s-agent (gtr/tencent) ← 等 server+edge 都完成
  │              └→ ✅ deploy-platform-operators ← 新增
  └→ validate-contract (与 deploy-gtr 并行)
```

## Files Changed

### 新增文件

```
edge/ansible/roles/argocd/tasks/main.yml            ✅ Created
edge/ansible/roles/argocd/templates/argocd-repo-secret.yaml.j2  ✅ Created
edge/ansible/roles/argocd/defaults/main.yml          ✅ Created
edge/ansible/roles/argocd/handlers/main.yml          ✅ Created
edge/ansible/deploy-platform-argocd.yml              ✅ Created
edge/ansible/deploy-platform-sealed-secrets.yml      ✅ Created
edge/ansible/verify-platform-argocd.yml              ✅ Created
edge/ansible/verify-platform-sealed-secrets.yml      ✅ Created
edge/ansible/verify-platform-tailscale-operator.yml  ✅ Created
platform/README.md                                   ✅ Created
platform/applications/kustomization.yaml             ✅ Created
platform/applications/sealed-secrets.yaml            ✅ Created
platform/applications/tailscale-operator.yaml        ✅ Created
platform/helm-values/tailscale-operator/values.yaml  ✅ Created
```

### 修改文件

```
.github/workflows/deploy-infra.yml       ✅ Added deploy-platform-operators job
k3s/README.md                            ✅ Updated platform components status
```

### 无需变更

```
.resource-manifest.yml                   ← 无变化（Argo CD 初期不走主机端口）
```

## Verification (One-Shot)

部署完成后，从 tailnet 内任一台设备执行：

```bash
# 1. Sealed Secrets 工作正常
k3s kubectl get secret test-secret -o jsonpath='{.data.dev-stdin}' | base64 -d
# 期望: hello-world

# 2. Tailscale Operator 工作正常
curl -sf -o /dev/null -w "Tailscale test: %{http_code}\n" \
  https://nginx-test-default.tail414c32.ts.net

# 3. Argo CD UI 已通过 Operator 暴露到 tailnet
curl -sf -o /dev/null -w "Argo CD: %{http_code}\n" \
  https://argocd-server-argocd.tail414c32.ts.net
# 期望: 200

# 4. Argo CD 已同步平台组件
k3s kubectl port-forward -n argocd svc/argocd-server 8080:80 &
argocd login localhost:8080 --username admin --password <password> --grpc-web
argocd app list | grep tailscale-operator
argocd app list | grep sealed-secrets
# 期望: Synced, Healthy
```

## Out Of Scope

- 业务应用 Helm chart 编写和迁移（由各应用 repo 在后续 issue 中完成）
- corp-finance-monitor 数据割接（见 issue #004）
- 共享存储（local PVC 以外）
- Envoy ↔ K3s 集成（当前架构中 Envoy 只处理边缘节点入口，不路由到 K3s 内）
- GTR 上裸机服务（Grafana/VM/VL/Envoy）迁移到 K3s（后续阶段）

## Acceptance Criteria

- [x] Argo CD 已安装在 K3s 中，可通过 `kubectl port-forward` 访问
- [x] Tailscale Operator 安装后，argocd-server 通过 `tailscale.com/expose` 注解自动获得 MagicDNS 域名
- [x] Sealed Secrets controller 可以解密一个提交到公开 Git 的 SealedSecret
- [x] Tailscale Operator 可以为带 `tailscale.com/expose: "true"` 注解的 Service 创建 MagicDNS 域名
- [x] Argo CD repo 凭证不存储在集群外的明文文件中
- [x] Sealed Secrets 私钥已备份到 `nas-deployment-vault`（sops 加密）
- [x] CI 中 `deploy-platform-operators` job 可在 K3s 部署完成后一次性执行
- [x] 平台组件可通过 Argo CD App-of-Apps 自动同步
- [x] 裸机 `tailscale serve` 服务不受影响（Grafana/VM/VL 继续正常工作）

## PR Linking

- Suggested PR title: `feat: bootstrap argocd sealed-secrets tailscale-operator on k3s`
- GitHub issue: `#4`
- PR body should include: `Closes #4`
- Planning doc path: `docs/issues/002-argocd-sealed-secrets-tailscale-operator.md`
