from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import SessionLocal
from app.models import User
from app.routes import attendance, auth, health, lessons, reports, rules, students, timetable_resources, users
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
app.include_router(rules.router, prefix="/api/v1")
app.include_router(timetable_resources.router, prefix="/api/v1")
app.include_router(lessons.router, prefix="/api/v1")
app.include_router(students.router, prefix="/api/v1")
app.include_router(attendance.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"service": "sps-student-dashboard", "status": "ok"}
