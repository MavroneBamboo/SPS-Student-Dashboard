#!/usr/bin/env bash
set -Eeuo pipefail

workspace="${GITHUB_WORKSPACE:?GitHub Actions workspace is required}"
revision="${GITHUB_SHA:?GitHub Actions commit SHA is required}"
run_id="${GITHUB_RUN_ID:-manual}"
staging_root="${SPS_STAGING_DIR:-${HOME:?HOME is required}/.local/share/sps-student-dashboard-staging}"
env_file="${SPS_STAGING_ENV_FILE:-${HOME:?HOME is required}/.config/sps-student-dashboard/staging.env}"

if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "GITHUB_SHA must be a full commit SHA" >&2
  exit 2
fi

workspace="$(realpath "$workspace")"
staging_root="$(realpath -m "$staging_root")"
if [[ "$staging_root" == "$workspace" || "$staging_root" == "$workspace/"* ]]; then
  echo "SPS_STAGING_DIR must be outside the checked-out repository" >&2
  exit 2
fi
if [[ ! -r "$env_file" ]]; then
  echo "Staging environment file is missing or unreadable: $env_file" >&2
  exit 2
fi
env_mode="$(stat -c '%a' "$env_file")"
if [[ "$env_mode" != "600" ]]; then
  echo "Staging environment file must not be readable or writable by group/others (chmod 600)" >&2
  exit 2
fi

checked_out_revision="$(git -C "$workspace" rev-parse HEAD)"
if [[ "$checked_out_revision" != "$revision" ]]; then
  echo "Checked-out revision does not match the workflow commit" >&2
  exit 2
fi

release_root="$staging_root/releases"
release="$release_root/$revision"
mkdir -p "$release_root"

if [[ ! -d "$release" ]]; then
  temporary_release="$(mktemp -d "$release_root/.deploy-${revision}-${run_id}.XXXXXX")"
  trap 'rm -rf -- "$temporary_release"' EXIT
  tar -C "$workspace" --exclude='./.git' --exclude='./.env' -cf - . | tar -C "$temporary_release" -xf -
  mv -- "$temporary_release" "$release"
  trap - EXIT
fi

compose=(
  docker compose
  --project-name sps-student-dashboard-staging
  --project-directory "$release"
  --env-file "$env_file"
  --file "$release/docker-compose.yml"
)

"${compose[@]}" config --quiet
"${compose[@]}" up --detach --build --remove-orphans

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error http://127.0.0.1:8080/health/ready >/dev/null; then
    echo "Staging revision $revision is healthy at http://localhost:8080/"
    exit 0
  fi
  sleep 2
done

"${compose[@]}" ps
echo "Staging did not become healthy; inspect service logs before retrying" >&2
exit 1
