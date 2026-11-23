from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import SessionLocal
from app.models import User
from app.observability import RequestCorrelationMiddleware
from app.routes import (
    attendance,
    auth,
    health,
    legacy_pri,
    lessons,
    reports,
    rules,
    setup,
    student_catalogs,
    student_imports,
    student_reference,
    students,
    timetable_exports,
    timetable_fixed_events,
    timetable_publications,
    timetable_resources,
    timetables,
    users,
)
from app.security import hash_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    with SessionLocal() as db:
        if db.query(User).filter(User.username == settings.bootstrap_username).first() is None:
            db.add(
                User(
                    username=settings.bootstrap_username,
                    password_hash=hash_password(settings.bootstrap_password),
                    role="Superuser",
                    must_change_password=True,
                )
            )
            db.commit()
    yield


app = FastAPI(title="SPS Student Dashboard API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(setup.router, prefix="/api/v1")
app.include_router(rules.router, prefix="/api/v1")
app.include_router(timetable_resources.router, prefix="/api/v1")
app.include_router(timetable_fixed_events.router, prefix="/api/v1")
app.include_router(lessons.router, prefix="/api/v1")
app.include_router(timetables.router, prefix="/api/v1")
app.include_router(timetable_exports.router, prefix="/api/v1")
app.include_router(timetable_publications.router, prefix="/api/v1")
app.include_router(legacy_pri.router, prefix="/api/v1")
app.include_router(students.router, prefix="/api/v1")
app.include_router(student_reference.router, prefix="/api/v1")
app.include_router(student_catalogs.router, prefix="/api/v1")
app.include_router(student_reference.attendance_mapping_router, prefix="/api/v1")
app.include_router(student_imports.router, prefix="/api/v1")
app.include_router(attendance.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="browser")


@app.middleware("http")
async def browser_security_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/ui", "/api/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self'; font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
    return response


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/ui/", status_code=303)


# Keep correlation outside FastAPI's server-error middleware so it can tag
# generic 500 responses without changing the framework's exception semantics.
app = RequestCorrelationMiddleware(app)
