#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKED = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()

ALLOWED_RUNTIME_SUFFIXES = (
    "secret.runtime.yml",
    "alert-notifications.runtime.yml",
)
PLACEHOLDER_HINTS = (
    "your_",
    "your-",
    "example",
    "placeholder",
    "changeme",
    "replace",
    "redacted",
    "sample",
    "dummy",
    "<",
    "{{",
)
ASSIGNMENT_PATTERNS = [
    (re.compile(r"^\s*k3s_cluster_token:\s*['\"]?(.+\S)", re.M), "k3s_cluster_token must stay in the private vault repo."),
    (re.compile(r"^\s*slock_ai_api_key:\s*['\"]?(.+\S)", re.M), "slock_ai_api_key must stay in the private vault repo."),
    (re.compile(r"^\s*shadowsocks_password:\s*['\"]?(.+\S)", re.M), "shadowsocks_password must stay in the private vault repo."),
    (re.compile(r"^\s*shadowtls_password:\s*['\"]?(.+\S)", re.M), "shadowtls_password must stay in the private vault repo."),
    (re.compile(r"^\s*hysteria2_password:\s*['\"]?(.+\S)", re.M), "hysteria2_password must stay in the private vault repo."),
    (re.compile(r"^\s*hysteria2_sal_obfs_password:\s*['\"]?(.+\S)", re.M), "hysteria2_sal_obfs_password must stay in the private vault repo."),
    (re.compile(r"^\s*mihomo_secret:\s*['\"]?(.+\S)", re.M), "mihomo_secret must stay in the private vault repo."),
    (re.compile(r"^\s*proxy_provider_url:\s*['\"]?(.+\S)", re.M), "Authenticated proxy provider URLs must stay in the private vault repo."),
    (re.compile(r"^\s*proxy_auth_password:\s*['\"]?(.+\S)", re.M), "proxy_auth_password must stay in the private vault repo."),
    (re.compile(r"^\s*edge_ca_root_key:\s*['\"]?(.+\S)", re.M), "CA private key material must stay in the private vault repo."),
    (re.compile(r"^\s*grafana_feishu_webhook_url:\s*['\"]?(.+\S)", re.M), "Grafana webhook URLs must stay in the private vault repo."),
]
LINE_PATTERNS = [
    (re.compile(r"AGE-SECRET-KEY-(?!.*\.{3})|BEGIN [A-Z0-9 ]*PRIVATE KEY(?!.*\.{3})|tskey-client-(?!.*\.{3})|sk_machine_(?!.*\.{3})|gho_[A-Za-z0-9_]+|ghp_[A-Za-z0-9_]+"), "Raw credential marker detected in the public repository."),
    (re.compile(r"https?://[^\s\"']+:[^\s\"'@]+@"), "Credentials embedded in URLs must stay in the private vault repo."),
    (re.compile(r"https://www\.feishu\.cn/flow/api/trigger-webhook/[A-Za-z0-9]+"), "Feishu webhook URLs must stay in the private vault repo."),
    (re.compile(r"Authorization:\s*[\"']?Bearer\s+[A-Za-z0-9._=-]{12,}", re.I), "Inline Bearer tokens must stay in the private vault repo."),
    (re.compile(r"Bearer\s+[A-Za-z0-9._=-]{12,}", re.I), "Inline Bearer tokens must stay in the private vault repo."),
    (re.compile(r"^\s*#\s*Plaintext password:", re.M), "Plaintext password notes must not be committed."),
]

violations: list[str] = []


def is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    return not normalized or any(hint in normalized for hint in PLACEHOLDER_HINTS)


for rel_path in TRACKED:
    if rel_path.endswith(ALLOWED_RUNTIME_SUFFIXES):
        continue
    if rel_path == "scripts/check-no-plaintext-secrets.py":
        continue

    file_path = ROOT / rel_path
    if not file_path.exists():
        continue

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue

    for pattern, message in ASSIGNMENT_PATTERNS:
        match = pattern.search(content)
        if match and not is_placeholder(match.group(1)):
            line_no = content.count("\n", 0, match.start()) + 1
            violations.append(f"{rel_path}:{line_no}: {message}")

    for pattern, message in LINE_PATTERNS:
        match = pattern.search(content)
        if match:
            line_no = content.count("\n", 0, match.start()) + 1
            violations.append(f"{rel_path}:{line_no}: {message}")

if violations:
    print("Plaintext secret guard failed:", file=sys.stderr)
    for violation in violations:
        print(f"  - {violation}", file=sys.stderr)
    sys.exit(1)

print("Plaintext secret guard passed.")
