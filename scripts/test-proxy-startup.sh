#!/usr/bin/env bash
set -Eeuo pipefail

image="${1:-sps-student-dashboard-proxy:ci}"
container="sps-proxy-startup-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
port="${PROXY_STARTUP_PORT:-18081}"

cleanup() {
  status=$?
  if [[ "$status" -ne 0 ]]; then
    docker logs "$container" >&2 || true
  fi
  docker rm --force "$container" >/dev/null 2>&1 || true
  return "$status"
}
trap cleanup EXIT

docker rm --force "$container" >/dev/null 2>&1 || true
docker run --detach --name "$container" --publish "127.0.0.1:${port}:80" "$image" >/dev/null

ready=false
for _ in $(seq 1 20); do
  if curl --fail --silent "http://127.0.0.1:${port}/prototype/" -o /dev/null; then
    ready=true
    break
  fi
  sleep 0.5
done

if [[ "$ready" != true ]]; then
  echo "Reverse proxy did not start and serve the packaged prototype without an API service present" >&2
  exit 1
fi

curl --fail --silent "http://127.0.0.1:${port}/prototype/reports/active-breakdown-by-category.csv" -o /dev/null
if [[ "$(docker inspect --format '{{.State.Status}}' "$container")" != "running" ]]; then
  echo "Reverse proxy exited before the startup smoke check completed" >&2
  exit 1
fi
