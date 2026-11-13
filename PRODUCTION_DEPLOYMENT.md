# Production deployment over HTTPS

Production Compose uses the Nginx proxy to terminate TLS. The existing default Compose configuration remains HTTP and binds to localhost for development and staging. Do not use the HTTP configuration for operational production data.

The production override uses Compose's `!override` merge tag and requires Docker Compose 2.24.0 or newer. Confirm with `docker compose version` before deploying.

## Certificate and environment setup

Obtain a trusted TLS certificate whose subject includes the public application hostname. Store its full-chain PEM file and matching private key on the Docker host, outside the repository. Restrict host permissions so only the deployment administrator and Docker daemon can read the private key. Keep certificate renewal under the organization's approved process.

Copy the TLS settings from `.env.production.example` into the protected environment file used by Compose. Set `PUBLIC_HOSTNAME`, the absolute certificate and key paths, and explicit HTTP/HTTPS bind addresses. Add the database, JWT, bootstrap and application-encryption secrets required by `.env.example`; use unique production values and `APP_ENV=production`. Do not commit the completed environment file or certificate/key material.

Production TLS configuration refuses startup if the hostname is invalid or either certificate file is absent or unreadable. Nginx validates that the certificate and private key can be loaded. The HTTP listener redirects only the configured hostname to HTTPS; unknown hostnames are closed. TLS is limited to TLS 1.2 and TLS 1.3 with an explicit ECDHE AES-GCM cipher list for TLS 1.2. HTTPS responses include HSTS and the existing content and framing security headers. The production overlay publishes only proxy ports 80 and 443; PostgreSQL remains on the internal Compose network and the API has no host-published port.

## Start and verify

Run these commands from the release directory containing the exact tested source revision:

```bash
docker compose \
  --project-name sps-student-dashboard-production \
  --file docker-compose.yml \
  --file docker-compose.production.yml \
  --env-file /etc/sps-student-dashboard/production.env \
  config --quiet

docker compose \
  --project-name sps-student-dashboard-production \
  --file docker-compose.yml \
  --file docker-compose.production.yml \
  --env-file /etc/sps-student-dashboard/production.env \
  up --build --detach

docker compose \
  --project-name sps-student-dashboard-production \
  --file docker-compose.yml \
  --file docker-compose.production.yml \
  --env-file /etc/sps-student-dashboard/production.env \
  ps
```

Verify `http://<PUBLIC_HOSTNAME>/` redirects to the configured HTTPS host, `https://<PUBLIC_HOSTNAME>/health/ready` returns ready, and the browser receives a valid certificate and HSTS. Check firewall rules and network access from an approved client. Never disable certificate verification for the production smoke check.

## Certificate renewal and rollback

After the approved certificate process replaces both host files, recreate the proxy so it loads the updated files:

```bash
docker compose \
  --project-name sps-student-dashboard-production \
  --file docker-compose.yml \
  --file docker-compose.production.yml \
  --env-file /etc/sps-student-dashboard/production.env \
  up --detach --no-deps --force-recreate proxy
```

Confirm HTTPS and the served certificate from an approved client after renewal. Retain the prior tested application release and the verified database backup for rollback. TLS termination does not replace secret custody, key rotation, access-controlled backups, restore drills, release approvals or network firewall controls.

CI creates a short-lived self-signed certificate only for proxy and Compose integration checks. It is never included in release artifacts.
