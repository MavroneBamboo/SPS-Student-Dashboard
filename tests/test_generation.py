from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.schemas import TEACHING_PERIODS, WEEKDAYS
from app.timetable_generation import generate_plan
from app.timetable_planning import validate_plan


def _snapshot(requirements):
    periods = [
        {"slot_code": code, "starts_at": start, "ends_at": end, "is_schedulable": code != "LUNCH"}
        for code, start, end in (
            ("P1", "08:30", "10:15"),
            ("P2", "10:15", "12:00"),
            ("LUNCH", "12:00", "13:25"),
            ("P3", "13:25", "15:10"),
            ("P4", "15:10", "16:55"),
        )
    ]
    snapshot = {"classes": {}, "teachers": {}, "requirements": {}, "subjects": {}}
    for requirement in requirements:
        row = {"instructional_class_id": 1, "subject_id": 1, "weekly_count": 1, "block_length": 1, **requirement}
        snapshot["requirements"][str(row["id"])] = row
        snapshot["classes"][str(row["instructional_class_id"])] = {
            "periods": deepcopy(periods),
            "rules": {
                day: {"rule": {"allowed_days": list(WEEKDAYS), "allowed_periods": list(TEACHING_PERIODS), "max_lessons_per_day": 4}}
                for day in WEEKDAYS
            },
        }
        snapshot["teachers"][str(row["teacher_id"])] = {"availability": {day: list(TEACHING_PERIODS) for day in WEEKDAYS}}
    return snapshot


def _repair_snapshot():
    snapshot = _snapshot([{"id": index, "teacher_id": index} for index in (1, 2, 3)])
    for teacher_id, periods in ((1, ["P1", "P2"]), (2, ["P1", "P3"]), (3, ["P1", "P3"])):
        snapshot["teachers"][str(teacher_id)]["availability"] = {day: periods if day == "MON" else [] for day in WEEKDAYS}
    return snapshot


def test_deterministic_repair_finds_complete_solution_after_greedy_dead_end():
    snapshot = _repair_snapshot()
    before = deepcopy(snapshot)
    result, report = generate_plan(snapshot, [], "FILL_PENDING", 2000)
    assert report["complete"] and not report["search_limit_reached"]
    assert report["search_attempts"] > 0
    assert {row["lesson_requirement_id"]: row["start_period"] for row in result} == {1: "P2", 2: "P1", 3: "P3"}
    assert generate_plan(snapshot, [], "FILL_PENDING", 2000) == (result, report)
    assert snapshot == before
    validate_plan(snapshot, result, require_complete=True)


def test_bounded_search_keeps_valid_greedy_baseline_and_reports_every_unplaced_block():
    snapshot = _repair_snapshot()
    result, report = generate_plan(snapshot, [], "FILL_PENDING", 1)
    assert not report["complete"] and report["search_limit_reached"]
    assert report["search_attempts"] == 1 and report["generated_periods"] == 2
    assert len(report["unplaced"]) == 1
    assert report["unplaced"][0]["reason"] == "CONFLICT_WITH_RESULT"
    assert any("class conflict" in reason for reason in report["unplaced"][0]["rejected_positions"])
    validate_plan(snapshot, result)


def test_block_remainders_lunch_gaps_and_rules_use_the_manual_validator():
    snapshot = _snapshot([{"id": 1, "teacher_id": 1, "weekly_count": 3, "block_length": 2}])
    snapshot["classes"]["1"]["periods"][1]["starts_at"] = "10:30"
    for day in WEEKDAYS:
        snapshot["classes"]["1"]["rules"][day]["rule"].update(allowed_days=["TUE"], max_lessons_per_day=3)
    result, report = generate_plan(snapshot, [], "FILL_PENDING", 2000)
    assert report["complete"]
    assert sorted(block["period_count"] for block in result) == [1, 2]
    assert all(block["weekday"] == "TUE" for block in result)
    double = next(block for block in result if block["period_count"] == 2)
    assert double["start_period"] == "P3"
    expanded = validate_plan(snapshot, result, require_complete=True)
    assert sum(len(slots) for slots in expanded.values()) == 3
    assert all(slot["slot_code"] != "LUNCH" for slots in expanded.values() for slot in slots)


def test_impossible_availability_has_explanations_and_no_false_completion():
    snapshot = _snapshot([{"id": 1, "teacher_id": 1, "weekly_count": 4, "block_length": 2}])
    snapshot["teachers"]["1"]["availability"] = {day: [] for day in WEEKDAYS}
    result, report = generate_plan(snapshot, [], "FILL_PENDING", 2000)
    assert result == [] and not report["complete"] and not report["search_limit_reached"]
    assert [row["period_count"] for row in report["unplaced"]] == [2, 2]
    assert all(row["reason"] == "NO_LEGAL_POSITION" for row in report["unplaced"])
    assert all(any("unavailable" in key for key in row["rejected_positions"]) for row in report["unplaced"])


def test_teacher_conflicts_use_actual_times_across_different_class_period_codes():
    snapshot = _snapshot([{"id": 1, "teacher_id": 1}, {"id": 2, "teacher_id": 1, "instructional_class_id": 2}])
    snapshot["classes"]["2"]["periods"][0].update(starts_at="07:00", ends_at="09:00")
    snapshot["classes"]["2"]["periods"][1].update(starts_at="09:00", ends_at="10:00")
    for class_id, allowed in (("1", ["P1"]), ("2", ["P2"])):
        for day in WEEKDAYS:
            snapshot["classes"][class_id]["rules"][day]["rule"].update(allowed_days=["MON"], allowed_periods=allowed)
    result, report = generate_plan(snapshot, [], "FILL_PENDING", 2000)
    assert len(result) == 1 and not report["complete"]
    assert any("teacher conflict" in reason for reason in report["unplaced"][0]["rejected_positions"])


def test_preserves_manual_blocks_by_default_and_locked_blocks_in_replace_mode():
    snapshot = _snapshot([{"id": 1, "teacher_id": 1, "weekly_count": 3}])
    before = [
        {
            "id": 10,
            "lesson_requirement_id": 1,
            "weekday": "FRI",
            "start_period": "P4",
            "period_count": 1,
            "is_locked": True,
            "note": "Fixed",
        },
        {
            "id": 11,
            "lesson_requirement_id": 1,
            "weekday": "THU",
            "start_period": "P3",
            "period_count": 1,
            "is_locked": False,
            "note": "Manual",
        },
    ]
    original = deepcopy(before)
    result, report = generate_plan(snapshot, before, "FILL_PENDING", 2000)
    assert result[:2] == before and report["preserved_placement_ids"] == [10, 11]
    assert report["removed_placement_ids"] == [] and report["generated_blocks"] == 1
    result, report = generate_plan(snapshot, before, "REPLACE_UNLOCKED", 2000)
    assert result[0] == before[0] and report["preserved_placement_ids"] == [10]
    assert report["removed_placement_ids"] == [11] and report["generated_blocks"] == 2
    assert before == original
    validate_plan(snapshot, result, require_complete=True)
    broken = [{**before[0], "period_count": 2, "start_period": "P2"}]
    with pytest.raises(HTTPException):
        generate_plan(snapshot, broken, "REPLACE_UNLOCKED", 2000)
