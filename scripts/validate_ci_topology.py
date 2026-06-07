#!/usr/bin/env python3
"""校验当前 K3s/Tailscale/CI 拓扑契约，防止稳定路径被误改回不可靠方案。"""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parent.parent
INVENTORY_PATH = ROOT / "edge/ansible/inventory-edge.ini"
GLOBAL_VARS_PATH = ROOT / "edge/ansible/group_vars/all/public.yml"
ALIYUN_VARS_PATH = ROOT / "edge/ansible/host_vars/aliyun/public.yml"
TENCENT_VARS_PATH = ROOT / "edge/ansible/host_vars/tencent.yml"

TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def find_inventory_host_vars(path: Path, hostname: str) -> dict[str, str]:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "[")):
            continue
        if not stripped.startswith(f"{hostname} "):
            continue

        parts = stripped.split()
        return {
            key: value
            for key, value in (part.split("=", 1) for part in parts[1:] if "=" in part)
        }
    raise KeyError(hostname)


def parse_url_host(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"非法 URL: {url}")
    return parsed.hostname


def is_cgnat_ip(value: str) -> bool:
    return ipaddress.ip_address(value) in TAILSCALE_CGNAT


def main() -> int:
    global_vars = load_yaml(GLOBAL_VARS_PATH)
    aliyun_vars = load_yaml(ALIYUN_VARS_PATH)
    tencent_vars = load_yaml(TENCENT_VARS_PATH)

    errors: list[str] = []
    notes: list[str] = []

    try:
        aliyun_inventory_vars = find_inventory_host_vars(INVENTORY_PATH, "aliyun")
    except KeyError as exc:
        errors.append(f"inventory 缺少 aliyun 主机定义: {exc}")
        aliyun_inventory_vars = {}

    aliyun_ansible_host = aliyun_inventory_vars.get("ansible_host", "")
    if not aliyun_ansible_host:
        errors.append("`inventory-edge.ini` 中 aliyun 缺少 `ansible_host`。")
    else:
        try:
            if is_cgnat_ip(aliyun_ansible_host):
                errors.append(
                    f"aliyun 的 `ansible_host={aliyun_ansible_host}` 落在 Tailscale CGNAT 段。"
                    "CI 管理面必须走公网 IP，不能依赖 aliyun↔gtr 的 Tailscale 直连。"
                )
        except ValueError as exc:
            errors.append(f"aliyun 的 `ansible_host` 不是合法 IP: {exc}")

    k3s_server_tailscale_ip = aliyun_vars.get("k3s_server_tailscale_ip", "")
    if not k3s_server_tailscale_ip:
        errors.append("`host_vars/aliyun/public.yml` 缺少 `k3s_server_tailscale_ip`。")
    else:
        try:
            if not is_cgnat_ip(k3s_server_tailscale_ip):
                errors.append(
                    f"`k3s_server_tailscale_ip={k3s_server_tailscale_ip}` 不在 Tailscale CGNAT 段。"
                )
        except ValueError as exc:
            errors.append(f"`k3s_server_tailscale_ip` 不是合法 IP: {exc}")

    k3s_server_url = global_vars.get("k3s_server_url", "")
    try:
        k3s_server_url_host = parse_url_host(k3s_server_url)
    except ValueError as exc:
        errors.append(str(exc))
        k3s_server_url_host = ""
    if k3s_server_url_host and k3s_server_tailscale_ip and k3s_server_url_host != k3s_server_tailscale_ip:
        errors.append(
            "`group_vars/all/public.yml` 中 `k3s_server_url` 必须指向 "
            f"`k3s_server_tailscale_ip`。当前为 {k3s_server_url_host} != {k3s_server_tailscale_ip}。"
        )

    tls_sans = aliyun_vars.get("k3s_server_tls_sans", []) or []
    if k3s_server_tailscale_ip and k3s_server_tailscale_ip not in tls_sans:
        errors.append("`k3s_server_tls_sans` 必须包含 aliyun 的 Tailscale IP。")
    if aliyun_ansible_host and aliyun_ansible_host not in tls_sans:
        errors.append("`k3s_server_tls_sans` 必须包含 aliyun 的公网管理 IP。")

    if aliyun_vars.get("k3s_prereq_tailscale_nodivert") is not True:
        errors.append(
            "aliyun 必须保持 `k3s_prereq_tailscale_nodivert: true`，"
            "否则云厂商 100.x 网段冲突会再次导致 SSH/控制面失联。"
        )

    tencent_server_url = tencent_vars.get("k3s_agent_server_url", "")
    try:
        tencent_server_host = parse_url_host(tencent_server_url)
    except ValueError as exc:
        errors.append(str(exc))
        tencent_server_host = ""
    if tencent_server_host and aliyun_ansible_host and tencent_server_host != aliyun_ansible_host:
        errors.append(
            "tencent 的 `k3s_agent_server_url` 必须跟随 aliyun 的公网管理地址，"
            f"当前为 {tencent_server_host} != {aliyun_ansible_host}。"
        )

    notes.append(f"aliyun SSH 管理面: {aliyun_ansible_host or 'missing'}")
    notes.append(f"cluster 默认 API: {k3s_server_url or 'missing'}")
    notes.append(f"aliyun Tailscale IP: {k3s_server_tailscale_ip or 'missing'}")
    notes.append(f"tencent agent API override: {tencent_server_url or 'missing'}")

    if errors:
        print("CI TOPOLOGY VALIDATION FAILED")
        for item in notes:
            print(f"  - {item}")
        print()
        for item in errors:
            print(f"  x {item}")
        return 1

    print("CI TOPOLOGY VALIDATION PASSED")
    for item in notes:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
