#!/usr/bin/env bash
set -euo pipefail

APP_NAMESPACE="${APP_NAMESPACE:-argocd}"
APP_NAME="${APP_NAME:-mihomo-exit}"
WORKLOAD_NAMESPACE="${WORKLOAD_NAMESPACE:-networking}"
STATEFULSET_NAME="${STATEFULSET_NAME:-mihomo-exit-canary}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1" >&2
    exit 1
  }
}

need_cmd kubectl

echo "=== GitOps Align 校验: ${APP_NAME} ==="

sync_status="$(kubectl -n "${APP_NAMESPACE}" get application "${APP_NAME}" -o jsonpath='{.status.sync.status}')"
health_status="$(kubectl -n "${APP_NAMESPACE}" get application "${APP_NAME}" -o jsonpath='{.status.health.status}')"

echo "Application Sync:   ${sync_status}"
echo "Application Health: ${health_status}"

if [[ "${sync_status}" != "Synced" ]]; then
  echo "GitOps 未对齐: ArgoCD Application 不是 Synced" >&2
  exit 1
fi

if [[ "${health_status}" != "Healthy" ]]; then
  echo "GitOps 未对齐: ArgoCD Application 不是 Healthy" >&2
  exit 1
fi

for name in mihomo-exit-auth mihomo-exit-api mihomo-exit-providers; do
  kubectl -n "${WORKLOAD_NAMESPACE}" get sealedsecret "${name}" >/dev/null
  kubectl -n "${WORKLOAD_NAMESPACE}" get secret "${name}" >/dev/null
done

kubectl -n "${WORKLOAD_NAMESPACE}" rollout status "statefulset/${STATEFULSET_NAME}" --timeout=180s >/dev/null

kubectl -n "${WORKLOAD_NAMESPACE}" get service mihomo-api >/dev/null
kubectl -n "${WORKLOAD_NAMESPACE}" get service "${STATEFULSET_NAME}" >/dev/null

ready_replicas="$(kubectl -n "${WORKLOAD_NAMESPACE}" get statefulset "${STATEFULSET_NAME}" -o jsonpath='{.status.readyReplicas}')"
current_replicas="$(kubectl -n "${WORKLOAD_NAMESPACE}" get statefulset "${STATEFULSET_NAME}" -o jsonpath='{.status.currentReplicas}')"

echo "StatefulSet Ready:  ${ready_replicas:-0}/${current_replicas:-0}"

echo
echo "关键资源:"
kubectl -n "${WORKLOAD_NAMESPACE}" get sealedsecret,secret,service,statefulset,pod -l app=mihomo-exit-canary 2>/dev/null || true

echo
echo "GitOps Align 校验通过。"
