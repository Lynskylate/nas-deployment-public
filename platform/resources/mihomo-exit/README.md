# Mihomo Exit Canary

`platform/resources/mihomo-exit/` 存放 K3s 原生 `Mihomo + Tailscale exit node` Canary 的 GitOps 清单。

## 设计边界

- **并行 Canary**：不替换当前 `gtr` 宿主机版 `Mihomo + exit node`
- **Operator 只管入口**：`mihomo-api` Service 通过 Tailscale Operator 暴露
- **exit node 不走 Operator Connector**：由 `StatefulSet` 中的独立 `tailscaled` 容器承载
- **DNS 固定为 `redir-host`**：配合 tailnet 全局 DNS 切换，恢复域名级规则命中
- **Tailscale 状态走 PVC**：显式关闭 `TS_KUBE_SECRET`，避免容器回写 Kubernetes Secret
- **Tailscale 版本固定**：当前钉在 `v1.96.5`，避免 `stable` 漂移带来 Kubernetes 启动语义变化
- **注册凭据受 tailnet policy 约束**：若 `TS_AUTHKEY` 不能合法申请 `tag:k3s-exit-canary`，`tailscale up` 会直接失败

## 目录内容

- [canary.yaml](/mnt/z/workspace/nas-deployment-public/platform/resources/mihomo-exit/canary.yaml)：核心 K8s 清单
- `sealedsecret-*.yaml`：真实密封后的凭据文件，需按部署文档生成后补入本目录

## 需要额外生成的 SealedSecret

以下文件**不会**在公共仓库里放明文，需要先从 vault 或 Tailscale Admin 获取原始值，再用 `kubeseal` 生成：

- `sealedsecret-mihomo-exit-auth.yaml`
  - Secret 名：`mihomo-exit-auth`
  - Key：`TS_AUTHKEY`
  - 当前实现使用 Tailscale OAuth client secret 作为等价 `TS_AUTHKEY`
- `sealedsecret-mihomo-exit-api.yaml`
  - Secret 名：`mihomo-exit-api`
  - Key：`MIHOMO_API_SECRET`
- `sealedsecret-mihomo-exit-providers.yaml`
  - Secret 名：`mihomo-exit-providers`
  - Key：
    - `PROXY_PROVIDER_URL`
    - `SHADOWSOCKS_PASSWORD`
    - `SHADOWTLS_PASSWORD`
    - `HYSTERIA2_PASSWORD`
    - `HYSTERIA2_SAL_OBFS_PASSWORD`

完整生成步骤见 [docs/deployment/k3s-mihomo-exit-canary-guide.md](/mnt/z/workspace/nas-deployment-public/docs/deployment/k3s-mihomo-exit-canary-guide.md)。

## GitOps Align

部署完成后，不要保留任何只存在于集群中的临时变更。

- 所有变更先回写到 Git，再由 ArgoCD 同步
- 如果排障期间做过手工 `kubectl patch` / `kubectl edit`，完成后必须回写到仓库并重新同步
- 可使用 [scripts/verify-mihomo-exit-gitops-align.sh](/mnt/z/workspace/nas-deployment-public/scripts/verify-mihomo-exit-gitops-align.sh) 做最终对齐校验
