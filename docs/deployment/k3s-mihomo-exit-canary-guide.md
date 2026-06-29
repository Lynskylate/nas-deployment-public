# K3s 原生 Mihomo Exit Canary 部署指南

本文说明如何将 `platform/resources/mihomo-exit/` 中的 Canary 清单补齐为可部署状态，并完成 tailnet 侧的配套变更。

## 目标

- 在 K3s 内启动一套独立的 `Mihomo + Tailscale exit node` 出口平面
- 迁移期继续保留当前 `gtr` 宿主机版 `Mihomo + exit node`
- 通过 `redir-host` + tailnet 全局 DNS 切换，恢复域名级规则命中

## 1. 前置条件

- `Tailscale Operator` 已由 ArgoCD 正常运行
- `gtr` 节点已在 K3s 中可调度
- `kubectl` 能访问当前 K3s 集群
- `kubeseal` 已安装
- 私有 `nas-deployment-vault` 可解密

## 2. 生成 SealedSecret

以下三类 Secret 需要生成并放回 `platform/resources/mihomo-exit/` 目录。当前仓库已经生成好了对应 SealedSecret；只有在凭据轮换时才需要重新执行本节。

### 2.1 Tailscale 节点注册凭据

当前实现直接复用 vault 中的 `tailscale_operator_oauth_client_secret` 作为 `TS_AUTHKEY` 等价凭据。

```bash
TS_AUTHKEY=$(sops --decrypt /mnt/z/workspace/nas-deployment-vault/infra/tailscale-operator/oauth.sops.yml | \
  python3 -c 'import sys,yaml;print(yaml.safe_load(sys.stdin)["tailscale_operator_oauth_client_secret"])')

kubectl -n networking create secret generic mihomo-exit-auth \
  --from-literal=TS_AUTHKEY="${TS_AUTHKEY}" \
  --dry-run=client -o yaml | \
kubeseal --controller-namespace kube-system \
  --controller-name sealed-secrets -o yaml > \
  platform/resources/mihomo-exit/sealedsecret-mihomo-exit-auth.yaml
```

### 2.2 Mihomo API Secret

```bash
MIHOMO_API_SECRET=$(sops --decrypt /mnt/z/workspace/nas-deployment-vault/ansible/mihomo/group_vars/all/secret.sops.yml | \
  python3 -c 'import sys,yaml;print(yaml.safe_load(sys.stdin)["mihomo_secret"])')

kubectl -n networking create secret generic mihomo-exit-api \
  --from-literal=MIHOMO_API_SECRET="${MIHOMO_API_SECRET}" \
  --dry-run=client -o yaml | \
kubeseal --controller-namespace kube-system \
  --controller-name sealed-secrets -o yaml > \
platform/resources/mihomo-exit/sealedsecret-mihomo-exit-api.yaml
```

### 2.3 上游代理与订阅凭据

```bash
PROXY_PROVIDER_URL=$(sops --decrypt /mnt/z/workspace/nas-deployment-vault/ansible/mihomo/group_vars/all/secret.sops.yml | \
  python3 -c 'import sys,yaml;print(yaml.safe_load(sys.stdin)["proxy_provider_url"])')
SHADOWSOCKS_PASSWORD=$(sops --decrypt /mnt/z/workspace/nas-deployment-vault/ansible/mihomo/group_vars/all/secret.sops.yml | \
  python3 -c 'import sys,yaml;print(yaml.safe_load(sys.stdin)["shadowsocks_password"])')
SHADOWTLS_PASSWORD=$(sops --decrypt /mnt/z/workspace/nas-deployment-vault/ansible/mihomo/group_vars/all/secret.sops.yml | \
  python3 -c 'import sys,yaml;print(yaml.safe_load(sys.stdin)["shadowtls_password"])')
HYSTERIA2_PASSWORD=$(sops --decrypt /mnt/z/workspace/nas-deployment-vault/ansible/mihomo/group_vars/all/secret.sops.yml | \
  python3 -c 'import sys,yaml;print(yaml.safe_load(sys.stdin)["hysteria2_password"])')
HYSTERIA2_SAL_OBFS_PASSWORD=$(sops --decrypt /mnt/z/workspace/nas-deployment-vault/ansible/mihomo/group_vars/all/secret.sops.yml | \
  python3 -c 'import sys,yaml;print(yaml.safe_load(sys.stdin)["hysteria2_sal_obfs_password"])')

kubectl -n networking create secret generic mihomo-exit-providers \
  --from-literal=PROXY_PROVIDER_URL="${PROXY_PROVIDER_URL}" \
  --from-literal=SHADOWSOCKS_PASSWORD="${SHADOWSOCKS_PASSWORD}" \
  --from-literal=SHADOWTLS_PASSWORD="${SHADOWTLS_PASSWORD}" \
  --from-literal=HYSTERIA2_PASSWORD="${HYSTERIA2_PASSWORD}" \
  --from-literal=HYSTERIA2_SAL_OBFS_PASSWORD="${HYSTERIA2_SAL_OBFS_PASSWORD}" \
  --dry-run=client -o yaml | \
kubeseal --controller-namespace kube-system \
  --controller-name sealed-secrets -o yaml > \
platform/resources/mihomo-exit/sealedsecret-mihomo-exit-providers.yaml
```

## 3. Tailnet 策略变更

### 3.1 tagOwners / autoApprovers

在 Tailscale Access Controls 中补齐：

```json
{
  "tagOwners": {
    "tag:k3s-exit-canary": ["autogroup:admin"]
  },
  "autoApprovers": {
    "exitNode": {
      "tag:k3s-exit-canary": ["autogroup:admin"]
    }
  }
}
```

如果当前 tailnet 仍使用旧版策略语法，按同等语义配置即可；核心要求是 `tag:k3s-exit-canary` 能自动获批为 exit node。

### 3.2 grants

Canary 阶段只开放给测试设备或管理员：

```json
{
  "grants": [
    {
      "src": ["autogroup:admin"],
      "dst": ["autogroup:internet"],
      "ip": ["*"]
    }
  ]
}
```

如需更细粒度控制，可改成仅允许测试用户组使用。

## 4. 部署

```bash
git add platform/applications/mihomo-exit.yaml \
  platform/resources/mihomo-exit \
  docs/deployment/k3s-mihomo-exit-canary-guide.md

git commit -m "add k3s mihomo exit canary manifests"
git push
```

等待 ArgoCD 同步：

```bash
k3s kubectl -n argocd get application mihomo-exit
k3s kubectl -n networking get pods
k3s kubectl -n networking get svc
```

## 5. 获取 Canary 节点的 Tailscale IP

部署完成后，需要知道新 exit node 在 tailnet 中的固定 IP，后续 tailnet 全局 DNS 要指向它：

```bash
k3s kubectl -n networking exec sts/mihomo-exit-canary -c tailscale -- tailscale ip -4
```

记下该 IPv4 地址，例如 `100.x.y.z`。

## 6. 切换 tailnet 全局 DNS

在 Tailscale Admin Console 的 DNS 页面：

1. 将新的全局 nameserver 改为上一步拿到的 `100.x.y.z`
2. 开启 `Override DNS servers`
3. 保留回滚记录：当前 GTR 宿主机版 Mihomo DNS `100.121.0.67`

> `redir-host` 方案依赖客户端 DNS 查询先进入 Mihomo；不切全局 DNS，就无法稳定恢复 `GitHub` / `AI` / `Google` 等域名级规则命中。

## 7. 灰度验证

### 7.1 观察 Canary 状态

```bash
k3s kubectl -n networking logs sts/mihomo-exit-canary -c tailscale --tail=50
k3s kubectl -n networking logs sts/mihomo-exit-canary -c route-controller --tail=50
k3s kubectl -n networking logs sts/mihomo-exit-canary -c mihomo --tail=50
```

### 7.2 验证控制面入口

`mihomo-api` Service 通过 Tailscale Operator 暴露后，会获得单独的 MagicDNS 域名。可从以下位置查看：

```bash
k3s kubectl -n tailscale get pods -o wide
k3s kubectl -n networking get service mihomo-api -o yaml
```

随后用 Bearer Token 访问 API：

```bash
curl -H "Authorization: Bearer <MIHOMO_API_SECRET>" \
  https://<mihomo-api-magicdns>/version
```

### 7.3 让测试设备切到 Canary

```bash
tailscale set --exit-node=k3s-mihomo-exit-canary --exit-node-allow-lan-access
```

### 7.4 验证规则命中

- `github.com` 应命中 `GitHub`
- `openai.com` / `chatgpt.com` 应命中 `AI`
- 中国站点应命中 `DIRECT`
- `*.ts.net`、`100.x` peer、K3s `10.60/16` 与 `10.61/16` 不应进入代理

可通过 Mihomo API 查看：

```bash
curl -H "Authorization: Bearer <MIHOMO_API_SECRET>" \
  https://<mihomo-api-magicdns>/connections
curl -H "Authorization: Bearer <MIHOMO_API_SECRET>" \
  https://<mihomo-api-magicdns>/proxies
```

## 8. 回滚

### 8.1 回滚客户端出口

```bash
tailscale up --exit-node=
tailscale set --exit-node=gtr --exit-node-allow-lan-access
```

### 8.2 回滚 tailnet DNS

把 Tailscale DNS 全局 nameserver 恢复成宿主机版 Mihomo DNS：

```text
100.121.0.67
```

### 8.3 保留现网兜底

本方案默认**不修改**以下内容：

- `mihomo/ansible/deploy.yml`
- `mihomo/ansible/deploy-exitnode.yml`
- 当前 `gtr` 宿主机 exit node 身份与现有路由

因此回滚时不需要额外恢复宿主机配置。

## 9. GitOps Align

Canary 部署成功后，必须把集群状态重新收敛到 “Git 是唯一事实来源”。

### 9.1 原则

- 不保留只存在于集群里的临时改动
- 不依赖长期手工 `kubectl apply`
- 所有最终保留的配置都必须在本仓库中有对应声明

### 9.2 推荐流程

1. 确认 `platform/applications/mihomo-exit.yaml` 与 `platform/resources/mihomo-exit/` 中的清单就是最终想保留的状态
2. 如排障过程中做过手工 patch、临时加 annotation、改副本数或改 env，先把这些变更回写到仓库
3. 提交并 push 到主分支
4. 等待 ArgoCD 自动同步，或用 ArgoCD 手动触发一次 sync
5. 运行 GitOps 对齐校验脚本，确认 Application / SealedSecret / StatefulSet 都回到期望状态

### 9.3 校验命令

```bash
bash scripts/verify-mihomo-exit-gitops-align.sh
```

脚本会检查：

- `argocd` 中 `mihomo-exit` Application 为 `Synced`
- `argocd` 中 `mihomo-exit` Application 为 `Healthy`
- `networking` 中 3 个 `SealedSecret` 和对应 `Secret` 都存在
- `mihomo-exit-canary` StatefulSet rollout 完成
- `mihomo-api` 与 `mihomo-exit-canary` Service 存在

### 9.4 发现未对齐时的处理

- 如果是集群里被手工改过：把最终值回写到 Git，再让 ArgoCD 再同步一次
- 如果是 Git 里少了资源：补充清单并提交
- 如果是 ArgoCD 一直 `OutOfSync`：先看 `kubectl -n argocd get application mihomo-exit -o yaml` 的差异原因，再决定是修清单还是修集群
