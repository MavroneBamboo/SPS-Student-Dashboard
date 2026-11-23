import sqlite3
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import AttendanceSession
from app.routes.reports import dashboard


def test_dashboard_aggregates_sessions_without_large_id_bind_list(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard-aggregation.db'}")

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all(
                AttendanceSession(
                    session_date=date(2026, 1, 1) + timedelta(days=index),
                    session_type="MORNING",
                    class_name="Synthetic class",
                    expected_count=3,
                    created_by=1,
                )
                for index in range(13)
            )
            db.commit()

            connection = db.connection().connection.driver_connection
            connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 12)
            result = dashboard(
                db,
                {"username": "synthetic-operator"},
                class_name=None,
                institution=None,
                category=None,
                status="ACTIVE",
                academic_year=None,
                date_from=None,
                date_to=None,
            )

        assert result["attendance"]["sessions"] == 13
        assert result["attendance"]["expected"] == 39
        assert result["attendance"]["recorded"] == 0
        assert result["attendance"]["missing"] == 39
        assert len(result["attendance"]["trend"]) == 13
        assert result["attendance"]["trend"][0]["date"] == "2026-01-01"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
