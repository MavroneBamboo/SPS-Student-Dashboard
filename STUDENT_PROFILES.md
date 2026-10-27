# Student profile browser/API and extended intake increment

Operators sign in at the production root and select **Student profiles**. Search by identifier/name, class and status; results show 25 records per page with explicit previous/next controls. Open a record to load its current saved values and status history, or select **New student** to create one. No synthetic profile data is loaded into this workflow.

The form covers the profile fields from the supported student intake workbook plus a year-bound age snapshot. The identifier is normalized to uppercase on creation, unique across students and read-only on edit. Category/status remain validated text rather than a hard-coded workbook vocabulary; ACTIVE/INACTIVE are suggestions. `INSTN CLASS` is retained verbatim as `class_name` until controlled institution/class catalogs and their mapping are delivered. Operators can stage, preview and explicitly commit supported 2023 intake workbooks; see [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md) for file controls and update behavior.

## Workbook field mapping

The supplied `Student Intake 2023` header row contains 38 columns. The worksheet `S/N` is only a row sequence and is not stored as a business field. Data columns map as follows:

| Workbook column | API/profile field | Storage |
| --- | --- | --- |
| Pris No. | `pris_no` | Normalized unique identifier |
| CAT | `category` | Validated text |
| EDR/ROS | `edr_ros` | Text |
| IC | `ic_number` | Application-encrypted |
| NAME | `name` | Application-encrypted |
| INSTN CLASS | `class_name` | Source label retained verbatim |
| STATUS | `status` | Validated text with status history |
| STATUS EFFECTIVE | `status_effective` | Date with status history |
| ADM TYPE | `admission_type` | Text |
| EXAM LEVEL | `exam_level` | Text |
| DOB | `date_of_birth` | Application-encrypted |
| AGE IN AY'23 | `age_in_academic_year`, `academic_year` | Integer paired with year (`2023` for this workbook) |
| GENDER | `gender` | Application-encrypted |
| LANG 1 / LANG 2 | `language_1`, `language_2` | Text |
| MATH 1 / MATH 2 | `math_1`, `math_2` | Text |
| CPA | `cpa` | Text |
| SCI / HUM | `science`, `humanities` | Text |
| COM 1 / COM 2 / COM 3 | `commerce_1`, `commerce_2`, `commerce_3` | Text |
| AA | `aa` | Text |
| NATIONALITY / CITIZENSHIP | `nationality`, `citizenship` | Application-encrypted |
| BIRTHPLACE | `birthplace` | Application-encrypted |
| RELIGION / RACE / MARITAL STATUS | `religion`, `race`, `marital_status` | Application-encrypted |
| MCH / NOK NAME | `next_of_kin_name` | Application-encrypted |
| MCH / NOK NRIC | `next_of_kin_nric` | Application-encrypted |
| MCH / NOK RELATIONSHIP | `next_of_kin_relationship` | Application-encrypted |
| MCH / NOK CONTACT NUMBER | `next_of_kin_contact` | Application-encrypted |
| MCH / NOK ADDRESS (PORTS) | `next_of_kin_address_ports` | Application-encrypted |
| MCH / NOK ADDRESS (From Student) | `next_of_kin_address_from_student` | Application-encrypted |
| MCH / NOK CONTACT NUMBER (From Student) | `student_contact` | Application-encrypted |

Migration `20261027_0009` adds nullable columns and an academic-year index. It leaves existing profile columns and ciphertext unchanged. The API returns decrypted values only through Operator-authorized routes. Audit entries record changed field names and versions, never submitted personal values. Optional values can be cleared with `null`; age snapshots are bounded to 0–120 and should be paired with their source academic year. Age is not recalculated from DOB because the workbook age is a historical-year snapshot.

Name and date of birth continue to use authenticated application encryption. A blank DOB on edit explicitly clears it; other required text fields reject blank/null input. Every successful save refreshes the editor/history and search results. Committed profile/status changes become visible when refreshing the dashboard. No hard-delete operation is exposed.

## Edit and history contract

Migration `20261026_0006` adds `students.version`, setting existing rows to 1 without altering existing ciphertext or business fields. New records start at 1. Responses include `version`; `GET /api/v1/students/{id}` returns one current profile. `GET /students` retains its list response with `q`, `class_name`, `status`, `offset` and `limit` (default/max 100). Name search currently decrypts the filtered candidate rows before matching and slicing; large-data search optimization remains a performance gate.

`PATCH /api/v1/students/{id}` now **requires** `expected_version` and at least one supported changed field. Clients of the earlier foundation API must adopt this contract. The SQL update compares ID/version atomically and increments the version. A stale request returns 409 and leaves profile, history and audit unchanged. The browser preserves the attempted form values and offers **Reload saved profile**; it never silently overwrites the winning edit. Reload deliberately replaces local edits with the saved record.

A status change appends history and updates the current status/effective date in the same transaction. If the API caller omits the new date, the server uses today and stores that same date in both places. The browser requires an explicit date when creating/changing status. Changing only the current effective date is rejected so history is not silently detached from the displayed status; a dedicated historical correction workflow remains future work. Clearing DOB or changing name/class/category does not add a status event. Historical rows remain ordered by effective date and ID, including backdated entries. Saves/audit/history commit or roll back together, and responses are captured before releasing the write transaction.

Concurrent identifier creation returns a friendly 409 from either the preliminary lookup or database unique constraint. Backend profile access retains the foundation role checks (Operator, IT Administrator and Superuser; Executive denied). The browser exposes daily profile processing to Operators only. Narrowing support/bootstrap access and implementing explicitly granted operational permissions remain part of the required full permission-matrix hardening; UI hiding is not an authorization boundary.

## Session/privacy and verification

Profile search/editor/history DOM and form values are cleared on sign-out/expiry. A permission-denied response from a now-unauthorized account signs the browser out and clears its data. Older list/detail responses cannot replace a newer selection or restore a signed-out session. Dynamic values render as text. The local `students.js` module is packaged and verified in the production image.

CI adds API cases for versions/encrypted round trips, optional DOB clearing, effective-date consistency, immutable identifiers, invalid inputs, denied Executive access, filtering before paging, concurrent saves and rollback after an audit failure. The migration rehearsal checks existing business fields/ciphertext are preserved and existing versions initialize to 1. Chromium acceptance covers create/duplicate/edit/history, dashboard refresh, stale form preservation/reload, role revocation/data clearing and paging. Workbook staging/import is implemented for the 2023 sheet; class/catalog reconciliation, historical class assignment and the full operational permission model remain release requirements.
