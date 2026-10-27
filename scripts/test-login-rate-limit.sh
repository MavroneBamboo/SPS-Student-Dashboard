#!/usr/bin/env bash
set -euo pipefail

container_name="sps-login-limit-smoke-${GITHUB_RUN_ID:-local}-$$"
server_log="$(mktemp)"
server_pid=""

cleanup() {
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -f "$server_log"
}
trap cleanup EXIT

python3 -m http.server 8000 --bind 127.0.0.1 >"$server_log" 2>&1 &
server_pid=$!
for _ in $(seq 1 50); do
  if curl --silent --output /dev/null http://127.0.0.1:8000/; then
    break
  fi
  sleep 0.1
done

docker run --detach --name "$container_name" --network host --add-host app:127.0.0.1 \
  --volume "$PWD/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.27.3-alpine >/dev/null

throttled=false
for _ in $(seq 1 45); do
  status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'Content-Type: application/json' --data '{}' \
    http://127.0.0.1/api/v1/auth/login || true)"
  if [[ "$status" == "429" ]]; then
    throttled=true
    break
  fi
done

if [[ "$throttled" != true ]]; then
  docker logs "$container_name"
  echo "Nginx did not throttle repeated sign-in requests with HTTP 429." >&2
  exit 1
fi

other_status="$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1/api/v1/auth/me)"
if [[ "$other_status" != "404" ]]; then
  echo "The sign-in limit affected another API route (expected mock-upstream HTTP 404, got $other_status)." >&2
  exit 1
fi
