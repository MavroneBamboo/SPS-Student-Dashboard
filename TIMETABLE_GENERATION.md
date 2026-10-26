# Timetable generation API

Weekly drafts can be generated from their frozen configuration in both the API and the production timetable browser. Operators can fill pending lessons or explicitly replace unlocked lessons; the browser displays completion and unplaced requirements. Publishing coordination, fixed events, composite teacher groups and exports remain future work.

## Generate

Operators and IT Administrators call `POST /api/v1/timetable/versions/{id}/generate`:

```json
{"expected_revision":1,"mode":"FILL_PENDING","search_budget":2000}
```

`FILL_PENDING` is the default. It preserves every existing manual or generated block, its ID, lock and note, and fills only remaining requirements. `REPLACE_UNLOCKED` explicitly removes unlocked blocks and replans those requirements; locked blocks retain their IDs, cells, locations and notes. Approved versions cannot be generated into. There is no replace-locked option.

The response contains `timetable` (the saved grid, revision and pending requirements) and `generation` (the run report). A partial result is a successful planning run, not an approved timetable: `complete` is false, every unplaced block is reported and approval still fails. A repeat on a complete draft preserves its grid but creates an audited run and advances the revision. Reload before another command; stale revisions return 409.

## Planning contract

The algorithm version is `constrained-first-fit-repair-v1`. It splits weekly totals into full blocks plus a shorter remainder, enumerates Monday–Friday/P1–P4 positions through the manual-placement validator, orders blocks by fewest legal positions, longer length, requirement ID and block ordinal, and builds a deterministic first-fit baseline. If there are conflicts, iterative bounded search attempts to improve the number of newly placed teaching periods. Existing preserved blocks never move during search. The baseline is retained unless a better valid result is found; ties keep the first result. Identical snapshots, seeds and search budgets produce the same placement choices, excluding database-generated IDs and timestamps.

`search_budget` limits repair candidate/skip attempts, defaults to 2,000 and accepts 1–10,000. It does not count static position enumeration or the initial greedy pass and is not a wall-clock timeout. The search uses explicit frames rather than recursion. The result is revalidated as a whole before persistence. It respects per-date scheduling rules, daily limits, teacher availability, actual-time class/teacher clashes under inherited period overrides, lunch, gaps and block patterns. A search limit is reported explicitly; the system does not claim global infeasibility or optimality from a partial result.

Every operation first checks the draft's current configuration, client revision and stored block/cell consistency under the timetable transaction lock. Rule gaps, ambiguous/unresolved rules, stale snapshots, damaged cells and approved versions fail before generation writes. Generation, removed/added blocks, occupied cells, revision and audit report commit or roll back together. The response grid is captured before releasing the transaction lock so its revision corresponds to the run report.

## Reports and follow-up

Reports record algorithm/mode, previous/result revision, version ID, search budget/attempts/limit, preserved and removed placement IDs, generated block/period counts and an `unplaced` entry for every remaining block. Each entry identifies requirement, class, teacher, subject and block length. `NO_LEGAL_POSITION` means no position passes the static rules/availability/block checks; `CONFLICT_WITH_RESULT` means legal positions conflict with the retained result. `rejected_positions` groups validator messages and counts. These explanations describe the result and do not prove that another arrangement is impossible.

`GET /api/v1/timetable/versions/{id}/generation-reports?offset=0&limit=50` retrieves newest-first historical reports from the committed `timetable.generated` audit events, including actor, event ID and creation time. Limit is 1–100. Reports retain their original revision after later amendments; they must not be presented as the current grid's validation state. Operators/IT can read their accessible versions; Executives can read reports only after version approval. Bootstrap Superusers cannot plan timetables.

Operators can resolve partial results with manual amendments, revised reference data and a replacement draft, or explicit replanning of unlocked blocks. This increment does not automatically copy/rebase a stale snapshot or overwrite approved history.

## Verification

Pure planner tests cover deterministic repair beyond first-fit, explicit search exhaustion, full/remainder blocks, lunch/gaps, rules/daily limits, no legal availability, actual-time clashes across different period labels and manual/lock preservation. API tests cover saved reports/grid/revision, repeat runs, explicit replacement, approval restrictions, permissions, invalid inputs, stale revisions/configuration, damaged grids, simultaneous generation and rollback after a database failure. Chromium browser acceptance tests now cover manual placement, editing, locking, generation and approval, plus IT resource setup. Production-scale runtime measurements, teacher-oriented views and report exports remain outstanding.
