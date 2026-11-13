#!/usr/bin/env bash
set -Eeuo pipefail

image="${1:-sps-student-dashboard-proxy:ci}"
image_tag="${image##*:}"
project="sps-production-tls-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
temp_dir="$(mktemp -d)"
compose=(docker compose --project-name "$project" --file docker-compose.yml --file docker-compose.production.yml)

cleanup() {
  status=$?
  "${compose[@]}" --env-file "$temp_dir/production.env" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$temp_dir"
  return "$status"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -sha256 -days 1 -nodes \
  -keyout "$temp_dir/tls.key" \
  -out "$temp_dir/tls.crt" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost" >/dev/null 2>&1
chmod 600 "$temp_dir/tls.key"

http_port="$((18000 + ${GITHUB_RUN_ID:-80} % 1000))"
https_port="$((19000 + ${GITHUB_RUN_ID:-443} % 1000))"
cat > "$temp_dir/production.env" <<EOF
APP_ENV=production
APP_BUILD_SHA=$image_tag
POSTGRES_PASSWORD=ci-only-admin-password
DATABASE_ADMIN_URL=postgresql+psycopg://sps_app:ci-only-admin-password@db:5432/sps_dashboard
DATABASE_RUNTIME_PASSWORD=ci-only-runtime-password
DATABASE_URL=postgresql+psycopg://sps_runtime:ci-only-runtime-password@db:5432/sps_dashboard
JWT_SECRET=ci-only-jwt-secret-long-enough-for-production-config
BOOTSTRAP_PASSWORD=ci-only-bootstrap-password-long-enough
APP_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
PUBLIC_HOSTNAME=localhost
PRODUCTION_HTTP_BIND_ADDRESS=127.0.0.1
PRODUCTION_HTTPS_BIND_ADDRESS=127.0.0.1
PRODUCTION_HTTP_PORT=$http_port
PRODUCTION_HTTPS_PORT=$https_port
TLS_CERTIFICATE_HOST_PATH=$temp_dir/tls.crt
TLS_PRIVATE_KEY_HOST_PATH=$temp_dir/tls.key
EOF

"${compose[@]}" --env-file "$temp_dir/production.env" config --format json > "$temp_dir/compose.json"
compose_assertions='import json,sys; c=json.load(sys.stdin); s=c["services"]; assert sorted(p["target"] for p in s["proxy"]["ports"]) == [80,443]; assert s["proxy"]["environment"]["PROXY_TLS_ENABLED"] == "1"; assert s["app"]["environment"]["APP_ENV"] == "production"; assert s["migrate"]["environment"]["APP_ENV"] == "production"; assert not s["db"].get("ports"); assert not s["app"].get("ports"); assert list(s["app"]["networks"]) == ["private"]'
if command -v python3 >/dev/null 2>&1; then
  python3 -c "$compose_assertions" < "$temp_dir/compose.json"
else
  docker run --rm --interactive python:3.12-alpine python -c "$compose_assertions" < "$temp_dir/compose.json"
fi

"${compose[@]}" --env-file "$temp_dir/production.env" up --detach
http_headers="$temp_dir/http.headers"
https_headers="$temp_dir/https.headers"
https_body="$temp_dir/https.body"
ready=false
for _ in $(seq 1 120); do
  if curl --insecure --silent --show-error --output "$temp_dir/ready.json" \
    "https://localhost:$https_port/health/ready" 2>/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  "${compose[@]}" --env-file "$temp_dir/production.env" ps
  "${compose[@]}" --env-file "$temp_dir/production.env" logs --no-color
  echo "Production HTTPS stack did not become ready" >&2
  exit 1
fi
grep -q '"revision":"'"$image_tag"'"' "$temp_dir/ready.json"

curl --silent --show-error --header 'Host: localhost' --dump-header "$http_headers" \
  --output /dev/null "http://127.0.0.1:$http_port/"
grep -Eiq '^HTTP/[^ ]+ 308([[:space:]]|$)' "$http_headers"
grep -Eiq '^Location: https://localhost/' "$http_headers"
if curl --silent --show-error --header 'Host: attacker.example' --dump-header "$temp_dir/unknown-host.headers" \
  --output /dev/null "http://127.0.0.1:$http_port/" 2>/dev/null; then
  echo "Unknown HTTP host was not rejected" >&2
  exit 1
fi
if grep -Eiq '^HTTP/[^ ]+ 308([[:space:]]|$)' "$temp_dir/unknown-host.headers"; then
  echo "Unknown HTTP host received a redirect" >&2
  exit 1
fi

curl --insecure --silent --show-error --tlsv1.2 --tls-max 1.2 \
  --dump-header "$https_headers" --output "$https_body" \
  "https://localhost:$https_port/prototype/"
grep -Eiq '^HTTP/[^ ]+ 200([[:space:]]|$)' "$https_headers"
grep -Eiq '^Strict-Transport-Security: max-age=31536000' "$https_headers"
grep -Eiq '^X-Content-Type-Options: nosniff' "$https_headers"
grep -q 'SPS Student Dashboard' "$https_body"

echo "Production HTTPS Compose stack checks passed."
