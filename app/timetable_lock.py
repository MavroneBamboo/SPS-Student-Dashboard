from sqlalchemy import func, select
from sqlalchemy.orm import Session


def lock_timetable_configuration(db: Session) -> None:
    """Serialize configuration/requirement writes across production API processes.

    The transaction releases the PostgreSQL lock on commit or rollback. The SPS
    namespace is shared by period, cluster membership and lesson mutations so a
    concurrent configuration change cannot bypass requirement validation.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(0x535053, 1)))
