#!/bin/sh
set -eu

if [ "${PROXY_TLS_ENABLED:-0}" != "1" ]; then
  exit 0
fi

: "${PUBLIC_HOSTNAME:?PUBLIC_HOSTNAME must be set when production TLS is enabled}"
if [ "${#PUBLIC_HOSTNAME}" -gt 253 ] || ! printf '%s\n' "$PUBLIC_HOSTNAME" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$'; then
  echo "PUBLIC_HOSTNAME must be a valid DNS hostname" >&2
  exit 1
fi

if [ ! -s /run/secrets/tls_certificate ] || [ ! -r /run/secrets/tls_certificate ]; then
  echo "The TLS certificate must be mounted at /run/secrets/tls_certificate" >&2
  exit 1
fi
if [ ! -s /run/secrets/tls_private_key ] || [ ! -r /run/secrets/tls_private_key ]; then
  echo "The TLS private key must be mounted at /run/secrets/tls_private_key" >&2
  exit 1
fi

envsubst '${PUBLIC_HOSTNAME}' \
  < /etc/nginx/production.conf.template \
  > /etc/nginx/conf.d/default.conf
