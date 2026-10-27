#!/usr/bin/env bash
set -euo pipefail

name_suffix="${GITHUB_RUN_ID:-local}-$$"
container_name="sps-login-limit-smoke-${name_suffix}"
upstream_name="sps-login-limit-upstream-${name_suffix}"
network_name="sps-login-limit-network-${name_suffix}"
image_name="sps-login-limit-nginx:${name_suffix}"

cleanup() {
  docker rm -f "$container_name" "$upstream_name" >/dev/null 2>&1 || true
  docker network rm "$network_name" >/dev/null 2>&1 || true
  docker image rm "$image_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network_name" >/dev/null
docker run --detach --name "$upstream_name" --network "$network_name" --network-alias app \
  python:3.12-alpine python -m http.server 8000 --bind 0.0.0.0 >/dev/null

# Build from the deploy directory so the test does not depend on host bind-mount path semantics.
docker build --quiet --tag "$image_name" --file - deploy <<'DOCKERFILE'
FROM nginx:1.27.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
DOCKERFILE

docker create --name "$container_name" --network "$network_name" --publish 127.0.0.1::80 "$image_name" >/dev/null
docker start "$container_name" >/dev/null
published_port="$(docker port "$container_name" 80/tcp | sed 's/.*://')"

ready=false
for _ in $(seq 1 50); do
  status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    "http://127.0.0.1:${published_port}/api/v1/auth/me" || true)"
  if [[ "$status" == "404" ]]; then
    ready=true
    break
  fi
  sleep 0.1
done

if [[ "$ready" != true ]]; then
  docker logs "$container_name"
  docker logs "$upstream_name"
  echo "Nginx did not become ready against the mock API upstream." >&2
  exit 1
fi

throttled=false
for _ in $(seq 1 45); do
  status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'Content-Type: application/json' --data '{}' \
    "http://127.0.0.1:${published_port}/api/v1/auth/login" || true)"
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

other_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "http://127.0.0.1:${published_port}/api/v1/auth/me")"
if [[ "$other_status" != "404" ]]; then
  echo "The sign-in limit affected another API route (expected mock-upstream HTTP 404, got $other_status)." >&2
  exit 1
fi

echo "Login endpoint throttling passed; other API routes remain reachable."
