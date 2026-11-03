# WSL laptop staging deployment

This setup deploys the tested `main` revision to a staging stack running on the maintainer's WSL laptop. Pull request jobs remain on GitHub-hosted runners. Only a push to `main`, after the test, secret-scan and container jobs pass, can use the laptop runner.

This is an engineering staging environment. Use synthetic data only. It does not provide production TLS, backup/restore, approved retention, key rotation, or release rollback controls.

## Laptop prerequisites

1. Install and start Docker Desktop for Windows with its WSL 2 backend.
2. In Docker Desktop, enable **Settings > Resources > WSL Integration** for the Linux distribution used by the Actions runner.
3. In that WSL distribution, confirm `docker version` and `docker compose version` both work.
4. Keep the repository and the Actions runner under the Linux filesystem, such as `/home/<user>/src` and `/home/<user>/actions-runner`, rather than `/mnt/d`.
5. Keep Docker Desktop and WSL running when a deployment is expected. Enable Docker Desktop's **Start Docker Desktop when you sign in** setting. The laptop must have outbound access to GitHub Actions. Do not forward staging ports from the router.

Check whether systemd is active with `ps -p 1 -o comm=`. If it is not, add `[boot]` and `systemd=true` to `/etc/wsl.conf`, then run `wsl.exe --shutdown` from PowerShell and reopen the distribution before installing the runner service. [Microsoft's WSL systemd guide](https://learn.microsoft.com/windows/wsl/systemd) has the full steps.

## Staging secrets and first start

Create a private environment file for the runner account at:

```text
~/.config/sps-student-dashboard/staging.env
```

Generate a local file with unique values and no copied example secrets:

```bash
install -d -m 700 "$HOME/.config/sps-student-dashboard"
umask 077
admin_password="$(openssl rand -hex 24)"
runtime_password="$(openssl rand -hex 24)"
cat > "$HOME/.config/sps-student-dashboard/staging.env" <<EOF
APP_ENV=staging
STAGING_BIND_ADDRESS=127.0.0.1
JWT_SECRET=$(openssl rand -hex 32)
BOOTSTRAP_PASSWORD=$(openssl rand -hex 24)
POSTGRES_PASSWORD=${admin_password}
DATABASE_ADMIN_URL=postgresql+psycopg://sps_app:${admin_password}@db:5432/sps_dashboard
DATABASE_RUNTIME_PASSWORD=${runtime_password}
DATABASE_URL=postgresql+psycopg://sps_runtime:${runtime_password}@db:5432/sps_dashboard
APP_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
EOF
chmod 600 "$HOME/.config/sps-student-dashboard/staging.env"
```

For an existing staging environment file, retain its current `POSTGRES_PASSWORD` because it must continue to unlock the existing named database volume. Generate a separate URL-safe `runtime_password`, then set `DATABASE_RUNTIME_PASSWORD` to it and set `DATABASE_URL` to `postgresql+psycopg://sps_runtime:<runtime_password>@db:5432/sps_dashboard`. Set `DATABASE_ADMIN_URL` to the existing `sps_app` password. The migration service uses that admin URL to upgrade the schema and provision the restricted runtime account; the API receives only the runtime URL. Do not replace an existing staging secrets file with the first-start example. Do not use production secrets. The staging data volume and application encryption key must be retained together; changing or losing the key makes encrypted staging values unreadable.

The application validates staging/production configuration during process startup. It refuses short or built-in JWT/bootstrap credentials, CI/test placeholders, identical JWT and bootstrap secrets, SQLite or non-`sps_runtime` database URLs, short/placeholder runtime database passwords, malformed/duplicate Fernet keys, the built-in development encryption key and access-token lifetimes above 60 minutes. A deployment that fails this check should correct its protected environment file; do not weaken the checks or print secret values while diagnosing it.

For the initial manual smoke test, check out `main`, configure the environment file, then run from the repository:

```bash
docker compose --project-name sps-student-dashboard-staging \
  --env-file "$HOME/.config/sps-student-dashboard/staging.env" config --quiet
docker compose --project-name sps-student-dashboard-staging \
  --env-file "$HOME/.config/sps-student-dashboard/staging.env" up --build --detach
docker compose --project-name sps-student-dashboard-staging \
  --env-file "$HOME/.config/sps-student-dashboard/staging.env" ps
curl --fail http://localhost:8080/health/ready
```

Open `http://localhost:8080/` and complete bootstrap password rotation. The proxy binds to localhost by default; do not change it to a LAN address while using HTTP.

## GitHub runner and environment

1. In repository **Settings > Actions > Runners**, add a repository-level Linux x64 runner while signed in with an account that can administer runners. Follow GitHub's displayed installation and registration commands inside the chosen WSL distribution.
2. Add the custom runner label `sps-staging` (GitHub also supplies `self-hosted`, `linux` and `x64`). Configure the runner as a systemd service using GitHub's generated `svc.sh` instructions. The Docker Desktop integration must work for the same Linux user that runs the service. If WSL does not start automatically after a Windows restart, start the distribution after sign-in or configure Windows Task Scheduler to run `wsl.exe -d <distribution> --exec /bin/true`.
3. In **Settings > Environments**, create `staging` and restrict deployment branches to `main`. Add a required reviewer if you want a person to approve each staging deployment; otherwise, successful CI on a push to `main` deploys automatically.
4. Ensure `main` is protected and PR checks/review are required. Never add this runner label to pull request, fork, or untrusted branch jobs. A self-hosted runner can retain data between jobs and has access to the laptop's Docker daemon.

The `deploy-staging` job in `.github/workflows/ci.yml` has these gates. It checks out the exact tested commit, stages it under the runner account's `~/.local/share/sps-student-dashboard-staging/releases/<commit-sha>`, and deploys that immutable source snapshot using the runner-local environment file. The Postgres named volume uses a stable Compose project name and persists across code updates. A readiness request to `http://127.0.0.1:8080/health/ready` is the deployment smoke check.

The workflow does not publish an image to a registry; the laptop builds the staging image from the tested source revision. The application and proxy bind mounts point into the retained release directory rather than the disposable Actions workspace.

## Operations

```bash
docker compose --project-name sps-student-dashboard-staging \
  --project-directory "$HOME/.local/share/sps-student-dashboard-staging/releases/<commit-sha>" \
  --env-file "$HOME/.config/sps-student-dashboard/staging.env" \
  ps
```

The staging project name and its `postgres-data` volume are shared across revisions. Do not run `docker compose down --volumes` unless you intend to erase the staging database. Keep the local environment file and database volume backed up together if staging records need to survive a laptop failure. Staging currently has no automated backup/restore or rollback workflow; test migrations and recovery procedures before relying on this environment for anything beyond synthetic acceptance testing.
