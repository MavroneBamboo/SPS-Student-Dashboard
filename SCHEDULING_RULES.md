# Scheduling rules and planning resolution

Rules apply to stable instructional-class or cluster IDs for an academic year and an inclusive date range. Planning must resolve exactly one rule for every requested class. Unlike period inheritance, scheduling rules have no class-over-cluster priority: overlapping scopes are rejected.

## API

IT Administrators create, replace, bind and archive rules. Operators can read and resolve them. Executives and bootstrap Superusers cannot access draft-rule APIs.

Create with `POST /api/v1/timetable/rules`:

```json
{
  "academic_year": "2026",
  "target_type": "CLASS",
  "target_id": 1,
  "effective_from": "2026-01-01",
  "effective_to": "2026-12-31",
  "rule": {
    "schema_version": 1,
    "max_lessons_per_day": 4,
    "allowed_days": ["MON", "TUE", "WED", "THU", "FRI"],
    "allowed_periods": ["P1", "P2", "P3", "P4"]
  }
}
```

Use `target_type=CLUSTER` and a cluster ID for shared rules. Null `effective_to` means open-ended. Both date boundaries are inclusive; a succeeding rule may start the day after its predecessor ends. Allowed days/periods are nonempty and unique; lunch is excluded. Definition version 1 supports these three constraints and rejects unknown settings. Further constraint types require coordinated schema, planner and test changes.

List/read via `GET /rules` or `/rules/{id}` under the same API prefix. Listing supports academic year, `include_inactive`, offset and limit. Replace or bind with `PUT /rules/{id}` using the complete create payload plus `expected_version` and `is_active`. Archive with `DELETE /rules/{id}?expected_version=N`. Writes increment the edit version; stale requests return 409. Rule changes and audit events commit together.

Resolve using `POST /api/v1/timetable/rules/resolve`:

```json
{"academic_year":"2026","on_date":"2026-10-23","class_ids":[1,2]}
```

Every class must exist and be active. Success returns one validated rule ID, edit version, target and definition per class in request order. Missing/ambiguous rules, inactive clusters, invalid stored definitions and applicable unresolved legacy rules return 409 for the whole request. There is no partial result or arbitrary choice. Weekly draft creation and manual amendments now call this shared resolver for every teaching date and apply its constraints; see [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md). Automatic generation must use the same services in its future implementation.

## Legacy migration

Revision `0004` preserves existing text targets, definitions, dates and activity flags. Old rows receive `binding_state=UNRESOLVED`, null resource foreign keys and version 1. No name guessing or automatic deactivation occurs. An active unresolved rule in the requested year/date blocks planning because its affected classes are unknown. A reversed legacy date range blocks the whole academic year until corrected. IT must bind it with a full `PUT` payload or archive it. Invalid legacy JSON is displayed as null and remains preserved in the database until corrected.

New rules are `BOUND`, with class/cluster foreign keys. `target_key` is only a display snapshot; code renaming does not change identity. Future timetable versions must snapshot the resolved definition/version for historical reproducibility.

## Database and concurrency

The service rejects overlapping dates for identical targets and class/cluster scopes sharing a class. Membership changes perform the same checks. PostgreSQL foreign keys/check constraints protect targets, dates and versions; triggers also reject overlapping rules/memberships from writers bypassing the API. Statement triggers acquire the shared timetable transaction advisory lock before row validation. The app explicitly uses READ COMMITTED; triggers reject other isolation levels so stale transaction snapshots cannot bypass checks. SQLite has service validation but not production trigger/concurrency guarantees.

VOLATILE trigger functions obtain fresh query snapshots after waiting for a writer. See PostgreSQL's [function visibility rules](https://www.postgresql.org/docs/17/xfunc-volatility.html) and [transaction advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).

CI covers date boundaries/open ends, roles, atomic bulk resolution, legacy binding, direct database overlap rejection, concurrent class/cluster writes and membership/rule races. The upgrade-preservation rehearsal checks that legacy rule contents survive and become explicitly unresolved.
