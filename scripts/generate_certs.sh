#!/bin/bash
set -e

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$CERT_DIR"

if [ -f "$CERT_DIR/server.key" ] && [ -f "$CERT_DIR/server.crt" ]; then
    echo "Certs already exist at $CERT_DIR"
    exit 0
fi

openssl req -x509 -newkey rsa:4096 -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" -days 365 -nodes \
    -subj "/C=BD/ST=Dhaka/O=SurveillanceSystem/CN=localhost"

echo "Self-signed certs generated:"
echo "  Key:  $CERT_DIR/server.key"
echo "  Cert: $CERT_DIR/server.crt"
echo "For production, replace with real CA-signed certs."
