#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CA_DIR="$ROOT_DIR/pki/root-ca"
CA_KEY="$CA_DIR/root-ca.key"
CA_CERT="$CA_DIR/root-ca.crt"

mkdir -p "$CA_DIR"

if [[ -f "$CA_KEY" || -f "$CA_CERT" ]]; then
  echo "Root CA already exists at $CA_DIR"
  echo "- key:  $CA_KEY"
  echo "- cert: $CA_CERT"
  exit 0
fi

openssl genrsa -out "$CA_KEY" 4096
openssl req -x509 -new -nodes -key "$CA_KEY" -sha256 -days 3650 \
  -subj "/C=CN/O=GTR Edge/CN=GTR Edge Root CA" \
  -out "$CA_CERT"

chmod 600 "$CA_KEY"
chmod 644 "$CA_CERT"

echo "Created Root CA:"
echo "- key:  $CA_KEY"
echo "- cert: $CA_CERT"
