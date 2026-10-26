"""Deterministic first-fit planning with bounded, iterative repair search."""

from collections import Counter

from fastapi import HTTPException

from app.schemas import TEACHING_PERIODS, WEEKDAYS
from app.timetable_planning import pending_requirements, validate_plan

ALGORITHM = "constrained-first-fit-repair-v1"


def _conflict(snapshot: dict, plan: list[dict], candidate: dict) -> str | None:
    """Only the candidate's class and teacher can introduce a new conflict."""
    requirements = snapshot["requirements"]
    requirement = requirements[str(candidate["lesson_requirement_id"])]
    related = [
        block
        for block in plan
        if requirements[str(block["lesson_requirement_id"])]["instructional_class_id"] == requirement["instructional_class_id"]
        or requirements[str(block["lesson_requirement_id"])]["teacher_id"] == requirement["teacher_id"]
    ]
    try:
        validate_plan(snapshot, [*related, candidate])
    except HTTPException as exc:
        return str(exc.detail)
    return None


def generate_plan(snapshot: dict, before: list[dict], mode: str, search_budget: int) -> tuple[list[dict], dict]:
    """Return a valid best-found plan; never claim that limited search proves infeasibility."""
    validate_plan(snapshot, before)
    seed = [block for block in before if mode == "FILL_PENDING" or block["is_locked"]]
    removed = [block["id"] for block in before if block not in seed]
    tasks = []
    domains = {}
    static_failures = {}
    for pending in sorted(pending_requirements(snapshot, seed), key=lambda row: row["lesson_requirement_id"]):
        requirement_id = pending["lesson_requirement_id"]
        for length in pending["remaining_blocks"]:
            key = (requirement_id, length)
            if key not in domains:
                domains[key], failures = [], Counter()
                for day in WEEKDAYS:
                    for period in TEACHING_PERIODS:
                        candidate = {
                            "id": -1,
                            "lesson_requirement_id": requirement_id,
                            "weekday": day,
                            "start_period": period,
                            "period_count": length,
                            "is_locked": False,
                            "note": "",
                        }
                        reason = _conflict(snapshot, [], candidate)
                        if reason:
                            failures[reason] += 1
                        else:
                            domains[key].append(candidate)
                static_failures[key] = dict(sorted(failures.items()))
            tasks.append((key, len(tasks) + 1))
    tasks.sort(key=lambda task: (len(domains[task[0]]), -task[0][1], task[0][0], task[1]))
    options = [[{**candidate, "id": -task_id} for candidate in domains[key]] for key, task_id in tasks]

    # Retain a useful greedy baseline even if the repair budget is exhausted.
    best = []
    for candidates in options:
        candidate = next((row for row in candidates if _conflict(snapshot, [*seed, *best], row) is None), None)
        if candidate is not None:
            best.append(candidate)
    best_score = sum(block["period_count"] for block in best)
    available_total = sum(key[1] for key, _ in tasks if domains[key])
    attempts = 0
    limited = False
    if best_score < available_total:
        # Explicit frames avoid Python recursion limits for large requirement sets.
        suffix = [0] * (len(tasks) + 1)
        for index in range(len(tasks) - 1, -1, -1):
            suffix[index] = suffix[index + 1] + (tasks[index][0][1] if options[index] else 0)
        frames = [iter([*options[0], None])]
        path = []
        score = 0
        while frames:
            if attempts >= search_budget:
                limited = True
                break
            try:
                candidate = next(frames[-1])
            except StopIteration:
                frames.pop()
                if path:
                    previous = path.pop()
                    score -= previous["period_count"] if previous else 0
                continue
            attempts += 1
            if candidate is not None and _conflict(snapshot, [*seed, *(row for row in path if row)], candidate):
                continue
            path.append(candidate)
            score += candidate["period_count"] if candidate else 0
            if score > best_score:
                best = [row for row in path if row]
                best_score = score
            if best_score == available_total:
                break
            if len(path) < len(tasks) and score + suffix[len(path)] > best_score:
                frames.append(iter([*options[len(path)], None]))
            else:
                previous = path.pop()
                score -= previous["period_count"] if previous else 0

    after = [*seed, *best]
    validate_plan(snapshot, after)
    unplaced = []
    for pending in pending_requirements(snapshot, after):
        requirement = snapshot["requirements"][str(pending["lesson_requirement_id"])]
        for length in pending["remaining_blocks"]:
            key = (pending["lesson_requirement_id"], length)
            reasons = Counter()
            for candidate in domains[key]:
                reason = _conflict(snapshot, after, candidate)
                if reason:
                    reasons[reason] += 1
            unplaced.append(
                {
                    "lesson_requirement_id": pending["lesson_requirement_id"],
                    "instructional_class_id": requirement["instructional_class_id"],
                    "teacher_id": requirement["teacher_id"],
                    "subject_id": requirement["subject_id"],
                    "period_count": length,
                    "reason": "NO_LEGAL_POSITION" if not domains[key] else "CONFLICT_WITH_RESULT",
                    "rejected_positions": dict(sorted(reasons.items())) if domains[key] else static_failures[key],
                }
            )
    return after, {
        "algorithm": ALGORITHM,
        "mode": mode,
        "complete": not unplaced,
        "search_budget": search_budget,
        "search_attempts": attempts,
        "search_limit_reached": limited,
        "preserved_placement_ids": [block["id"] for block in seed],
        "removed_placement_ids": removed,
        "generated_blocks": len(best),
        "generated_periods": best_score,
        "unplaced": unplaced,
    }
