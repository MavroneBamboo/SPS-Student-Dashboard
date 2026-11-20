from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import engine


@pytest.mark.parametrize(
    ("session_types", "expected_count"),
    [(("MORNING", "AFTERNOON"), 2), (("MORNING", "FULL_DAY"), 1)],
)
@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL partial unique indexes are the concurrency authority")
def test_database_enforces_attendance_period_overlap_under_concurrency(session_types, expected_count):
    class_name = f"CONCURRENT-ATTENDANCE-{uuid4().hex[:10]}"
    session_date = date(2026, 11, 20)
    barrier = Barrier(2)

    def insert(session_type):
        try:
            with engine.begin() as connection:
                barrier.wait(timeout=10)
                connection.execute(
                    text(
                        """
                        INSERT INTO attendance_sessions
                            (session_date, session_type, class_name, expected_count, status, version,
                             roster_snapshot_state, created_by)
                        VALUES (:session_date, :session_type, :class_name, 1, 'OPEN', 1, 'LEGACY_PARTIAL', 1)
                        """
                    ),
                    {"session_date": session_date, "session_type": session_type, "class_name": class_name},
                )
            return True
        except IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(insert, session_types))

    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM attendance_sessions WHERE class_name = :class_name AND session_date = :session_date"),
            {"class_name": class_name, "session_date": session_date},
        ).scalar_one()

    assert sum(outcomes) == expected_count
    assert count == expected_count
