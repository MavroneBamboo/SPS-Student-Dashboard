import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import AuditEvent, ClassClusterMember, InstructionalClass, SchedulingRule
from app.scheduling_rules import resolve_rules
from app.schemas import RuleResolutionRequest

BASE = "/api/v1/timetable"


@pytest.fixture
def rules_context(lesson_context):
    client, headers, lesson = lesson_context
    payload = {
        "academic_year": f"RULE-{lesson['instructional_class_id']}",
        "target_type": "CLASS",
        "target_id": lesson["instructional_class_id"],
        "effective_from": "2026-01-01",
        "effective_to": "2026-06-30",
        "rule": {"max_lessons_per_day": 3},
    }
    return client, headers, payload


def _cluster(client, headers):
    result = client.post(f"{BASE}/clusters", json={"code": f"G{uuid4().hex[:10]}", "name": "Rule Cluster"}, headers=headers["admin"])
    assert result.status_code == 201
    return result.json()["id"]


def _resolve(client, headers, payload, on_date="2026-03-01"):
    return client.post(
        f"{BASE}/rules/resolve",
        json={
            "academic_year": payload["academic_year"],
            "class_ids": [payload["target_id"]],
            "on_date": on_date,
        },
        headers=headers["operator"],
    )


def _db_rule(payload, **changes):
    return SchedulingRule(
        **{
            "academic_year": payload["academic_year"],
            "target_type": payload["target_type"],
            "target_key": "snapshot",
            "instructional_class_id": payload["target_id"] if payload["target_type"] == "CLASS" else None,
            "cluster_id": payload["target_id"] if payload["target_type"] == "CLUSTER" else None,
            "effective_from": date.fromisoformat(payload["effective_from"]),
            "effective_to": date.fromisoformat(payload["effective_to"]) if payload.get("effective_to") else None,
            "binding_state": "BOUND",
            "version": 1,
            "is_active": True,
            "created_by": 0,
            "rule_json": json.dumps(payload.get("rule", {})),
            **changes,
        }
    )


def test_rule_permissions_lifecycle_and_inclusive_date_resolution(rules_context):
    client, headers, payload = rules_context
    assert _resolve(client, headers, payload).status_code == 409
    for role in ("operator", "executive"):
        assert client.post(f"{BASE}/rules", json=payload, headers=headers[role]).status_code == 403
    for role in ("executive",):
        assert client.get(f"{BASE}/rules", headers=headers[role]).status_code == 403
    superuser_rule = client.post(
        f"{BASE}/rules", json={**payload, "academic_year": f"SU-{payload['academic_year']}"}, headers=headers["superuser"]
    )
    assert superuser_rule.status_code == 201
    assert client.get(f"{BASE}/rules", headers=headers["superuser"]).status_code == 200
    created = client.post(f"{BASE}/rules", json=payload, headers=headers["admin"])
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]
    assert created.json()["binding_state"] == "BOUND"
    assert _resolve(client, headers, payload, "2026-01-01").json()[0]["rule_id"] == rule_id
    assert _resolve(client, headers, payload, "2026-06-30").status_code == 200
    assert _resolve(client, headers, payload, "2026-07-01").status_code == 409
    assert client.post(f"{BASE}/rules", json={**payload, "effective_from": "2026-06-30"}, headers=headers["admin"]).status_code == 409
    assert (
        client.post(
            f"{BASE}/rules", json={**payload, "effective_from": "2026-07-01", "effective_to": None}, headers=headers["admin"]
        ).status_code
        == 201
    )
    assert _resolve(client, headers, payload, "9999-12-31").status_code == 200
    changed = client.put(
        f"{BASE}/rules/{rule_id}",
        json={**payload, "expected_version": 1, "is_active": True, "rule": {"max_lessons_per_day": 2}},
        headers=headers["admin"],
    )
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert _resolve(client, headers, payload).json()[0]["rule"]["max_lessons_per_day"] == 2
    assert client.delete(f"{BASE}/rules/{rule_id}?expected_version=1", headers=headers["admin"]).status_code == 409
    assert client.delete(f"{BASE}/rules/{rule_id}?expected_version=2", headers=headers["admin"]).status_code == 200
    assert _resolve(client, headers, payload).status_code == 409
    restored = client.put(f"{BASE}/rules/{rule_id}", json={**payload, "expected_version": 3, "is_active": True}, headers=headers["admin"])
    assert restored.status_code == 200
    assert restored.json()["version"] == 4
    assert (
        client.put(
            f"{BASE}/rules/{rule_id}", json={**payload, "expected_version": 1, "is_active": True}, headers=headers["admin"]
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "scheduling_rule", AuditEvent.entity_id == str(rule_id))
        ).all()
        assert len(events) == 4  # create, update, archive, restore; stale attempts produce no writes


def test_rule_schema_and_reference_checks(rules_context):
    client, headers, payload = rules_context
    for definition in (
        {"allowed_periods": ["LUNCH"]},
        {"allowed_periods": ["P1", "P1"]},
        {"allowed_days": ["MON", "MON"]},
        {"allowed_days": []},
        {"max_lessons_per_day": 0},
        {"maxLessonsPerDay": 4},
        {"schema_version": 2},
    ):
        response = client.post(f"{BASE}/rules", json={**payload, "rule": definition}, headers=headers["admin"])
        assert response.status_code == 422, response.text
    for changes in ({"target_id": 2147483647}, {"effective_to": "2025-12-31"}, {"academic_year": " "}, {"target_key": "text-only"}):
        assert client.post(f"{BASE}/rules", json={**payload, **changes}, headers=headers["admin"]).status_code == 422
    duplicate_ids = {"academic_year": payload["academic_year"], "on_date": "2026-03-01", "class_ids": [payload["target_id"]] * 2}
    assert client.post(f"{BASE}/rules/resolve", json=duplicate_ids, headers=headers["operator"]).status_code == 422


def test_bulk_resolution_requires_all_classes_and_preserves_requested_order(rules_context):
    client, headers, payload = rules_context
    other = client.post(f"{BASE}/classes", json={"code": f"B{uuid4().hex[:10]}", "name": "Second Planned Class"}, headers=headers["admin"])
    assert other.status_code == 201
    other_id = other.json()["id"]
    assert client.post(f"{BASE}/rules", json=payload, headers=headers["admin"]).status_code == 201
    request = {"academic_year": payload["academic_year"], "on_date": "2026-03-01", "class_ids": [other_id, payload["target_id"]]}
    missing = client.post(f"{BASE}/rules/resolve", json=request, headers=headers["operator"])
    assert missing.status_code == 409
    assert missing.json()["detail"]["classes"] == [{"instructional_class_id": other_id, "reason": "missing", "rule_ids": []}]
    assert client.post(f"{BASE}/rules", json={**payload, "target_id": other_id}, headers=headers["admin"]).status_code == 201
    resolved = client.post(f"{BASE}/rules/resolve", json=request, headers=headers["operator"])
    assert resolved.status_code == 200
    assert [row["instructional_class_id"] for row in resolved.json()] == request["class_ids"]


def test_class_cluster_overlap_and_membership_changes_are_rejected(rules_context):
    client, headers, payload = rules_context
    cluster_id = _cluster(client, headers)
    cluster_payload = {**payload, "target_type": "CLUSTER", "target_id": cluster_id}
    class_rule = client.post(f"{BASE}/rules", json=payload, headers=headers["admin"])
    assert class_rule.status_code == 201
    assert client.post(f"{BASE}/rules", json=cluster_payload, headers=headers["admin"]).status_code == 201  # empty cluster
    member_url = f"{BASE}/clusters/{cluster_id}/classes"
    assert client.post(member_url, json={"instructional_class_id": payload["target_id"]}, headers=headers["admin"]).status_code == 409
    if engine.dialect.name == "postgresql":
        with SessionLocal() as db:
            db.add(ClassClusterMember(cluster_id=cluster_id, instructional_class_id=payload["target_id"], created_by=0))
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
    assert client.delete(f"{BASE}/rules/{class_rule.json()['id']}?expected_version=1", headers=headers["admin"]).status_code == 200
    assert client.post(member_url, json={"instructional_class_id": payload["target_id"]}, headers=headers["admin"]).status_code == 201
    resolved = _resolve(client, headers, payload)
    assert resolved.status_code == 200
    assert resolved.json()[0]["target_type"] == "CLUSTER"
    assert client.post(f"{BASE}/rules", json=payload, headers=headers["admin"]).status_code == 409
    if engine.dialect.name == "postgresql":
        with SessionLocal() as db:
            db.add(_db_rule(payload))
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()


def test_legacy_rule_requires_explicit_binding_and_invalid_definition_blocks_resolution(rules_context):
    client, headers, payload = rules_context
    with SessionLocal() as db:
        legacy = _db_rule(
            payload,
            binding_state="UNRESOLVED",
            instructional_class_id=None,
            target_key="Legacy display name",
            rule_json='{"maxLessonsPerDay":4}',
            effective_to=date(2025, 12, 31),  # a malformed legacy window must not disappear from resolution
        )
        db.add(legacy)
        db.commit()
        rule_id = legacy.id
    blocked = _resolve(client, headers, payload)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["rule_ids"] == [rule_id]
    legacy_view = client.get(f"{BASE}/rules/{rule_id}", headers=headers["admin"])
    assert legacy_view.json()["target_key"] == "Legacy display name"
    assert legacy_view.json()["rule"] == {"maxLessonsPerDay": 4}
    bound = client.put(f"{BASE}/rules/{rule_id}", json={**payload, "expected_version": 1, "is_active": True}, headers=headers["admin"])
    assert bound.status_code == 200, bound.text
    assert bound.json()["binding_state"] == "BOUND"
    assert _resolve(client, headers, payload).status_code == 200
    with SessionLocal() as db:
        row = db.get(SchedulingRule, rule_id)
        row.rule_json = "invalid-json"
        db.commit()
    assert _resolve(client, headers, payload).status_code == 409


def test_direct_postgresql_rule_writers_cannot_race_past_overlap_checks(rules_context):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production trigger concurrency requires PostgreSQL")
    client, headers, payload = rules_context
    cluster_id = _cluster(client, headers)
    assert (
        client.post(
            f"{BASE}/clusters/{cluster_id}/classes", json={"instructional_class_id": payload["target_id"]}, headers=headers["admin"]
        ).status_code
        == 201
    )
    barrier = Barrier(2)

    def insert(kind):
        barrier.wait(timeout=10)
        with SessionLocal() as db:
            rule_payload = payload if kind == "CLASS" else {**payload, "target_type": "CLUSTER", "target_id": cluster_id}
            db.add(_db_rule(rule_payload))
            try:
                db.commit()
                return "created"
            except IntegrityError:
                db.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(insert, ("CLASS", "CLUSTER")))
    assert sorted(results) == ["created", "rejected"]
    assert _resolve(client, headers, payload).status_code == 200


def test_postgresql_rule_foreign_keys_and_supported_isolation_are_enforced(rules_context):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production database safeguards require PostgreSQL")
    _, _, payload = rules_context
    with SessionLocal() as db:
        db.add(_db_rule(payload, instructional_class_id=2147483647))
        with pytest.raises(IntegrityError) as error:
            db.flush()
        assert error.value.orig.sqlstate == "23503"
        db.rollback()
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(bind=connection) as db:
            db.add(_db_rule(payload))
            with pytest.raises(DBAPIError) as error:
                db.flush()
            assert "READ COMMITTED" in str(error.value)
            db.rollback()


def test_rule_creation_and_membership_race_cannot_commit_overlapping_scopes(rules_context):
    client, headers, payload = rules_context
    cluster_id = _cluster(client, headers)
    assert client.post(f"{BASE}/rules", json=payload, headers=headers["admin"]).status_code == 201
    barrier = Barrier(2)

    def write(kind):
        barrier.wait(timeout=10)
        if kind == "rule":
            return client.post(
                f"{BASE}/rules", json={**payload, "target_type": "CLUSTER", "target_id": cluster_id}, headers=headers["admin"]
            )
        return client.post(
            f"{BASE}/clusters/{cluster_id}/classes", json={"instructional_class_id": payload["target_id"]}, headers=headers["admin"]
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ("rule", "membership")))
    assert sorted(result.status_code for result in results) == [201, 409]


def test_resolver_rejects_ambiguous_imported_store():
    database = create_engine("sqlite://")
    try:
        Base.metadata.create_all(database)
        with Session(database) as db:
            instructional_class = InstructionalClass(code="AMB", name="Ambiguous Class", reporting_order=0, created_by=0)
            db.add(instructional_class)
            db.flush()
            payload = {
                "academic_year": "2026",
                "target_type": "CLASS",
                "target_id": instructional_class.id,
                "effective_from": "2026-01-01",
                "effective_to": None,
            }
            db.add_all([_db_rule(payload), _db_rule(payload)])
            db.commit()  # simulate a corrupted imported store without PostgreSQL trigger protection
            with pytest.raises(HTTPException) as error:
                resolve_rules(db, RuleResolutionRequest(academic_year="2026", class_ids=[instructional_class.id], on_date="2026-03-01"))
            assert error.value.status_code == 409
            assert error.value.detail["classes"][0]["reason"] == "ambiguous"
    finally:
        database.dispose()
