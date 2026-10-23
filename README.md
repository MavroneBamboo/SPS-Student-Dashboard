# SPS Student Dashboard

This repository contains the production system under construction and the approved HTML prototype in [`prototype/`](prototype/).

## Run the foundation locally

Copy `.env.example` to `.env` and replace the sample secrets. Then run:

```powershell
docker compose up --build
```

Open `http://localhost:8080/prototype/index.html` for the prototype or `http://localhost:8080/docs` for the API documentation.

The initial bootstrap identity is controlled by `BOOTSTRAP_USERNAME` and `BOOTSTRAP_PASSWORD`. It is seeded as a Superuser in setup state and must be changed/rotated before operational use. PostgreSQL is on a private Compose network and has no published host port.

## Current implemented slice

- Docker Compose services for NGINX, FastAPI and PostgreSQL.
- Live/readiness health endpoints.
- Bootstrap Superuser login with short-lived signed JWT access tokens.
- PBKDF2 password hashing.
- Protected scheduling-rule API with duplicate/overlap rejection.
- Protected student intake API with duplicate `Pris No.` rejection and application-encrypted name/date-of-birth fields.
- Attendance session and record API with class eligibility checks, duplicate prevention, correction reasons, record review and session close control.
- CI test workflow and container-based pytest suite.

This is the foundation only. Student intake, attendance, reports, migrations, encrypted sensitive fields, worker jobs and the production frontend are delivered in subsequent vertical slices.
