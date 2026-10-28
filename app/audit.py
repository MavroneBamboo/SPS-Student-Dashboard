import json

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record_event(db: Session, actor_id: int, action: str, entity_type: str, entity_id: str, details: dict | None = None) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
    )
    db.add(event)
    return event
