# Student reference catalogs

## Purpose

IT Administrators and the Superuser can maintain category, institution, and academic-year labels from **Reference data**. The API is under `/api/v1/student-reference/catalogs/` with `categories`, `institutions`, and `academic-years` resources. Operators and Executives may read active values; only IT Administrators and the Superuser may create, rename, archive, or reactivate them.

Catalog labels are normalized with Unicode NFKC, collapsed whitespace, and case folding for uniqueness. Updates carry an expected version and use a compare-and-swap write; stale edits return 409. Changes are audited. Values are archived rather than deleted, preserving identifiers and history. Academic-year values can optionally carry effective dates. The migration backfills distinct existing student categories and academic years found in students and timetable configuration without changing those source records. Institution values begin empty because the current student model and supplied import path do not yet record a student institution.

## Profile and intake integration

Student profile creation and reference-field changes require active category, academic-year, and (when supplied) institution values. The API canonicalizes a submitted label to its managed display name and uses a row lock while validating it. Historical values may remain on existing profiles after archival; unchanged values are preserved, while assigning an inactive value to a new or changed profile is rejected. Catalog labels already used by profiles cannot be renamed, preventing reports and saved profiles from silently diverging; create a replacement value and update profiles explicitly.

The profile workspace uses selectors populated from the API, includes institution in search/results, and exposes active-student totals by institution with a matching dashboard filter. Institution is optional because the supported Student Intake 2023 workbook has no institution column; operators assign it from the controlled selector when known.

Intake preview validates `CAT` and any academic-year value against active catalogs, stores the catalog ID/name/version with the encrypted staged row, and canonicalizes the value. Commit locks and rechecks these snapshots; a catalog change or archive after preview rejects the whole batch and requires a fresh preview. The workbook does not supply institution, so blank import cells preserve the existing institution and new imported profiles start unassigned.

## Verification

API coverage checks role access, Unicode/case/whitespace duplicate handling, date validation, expected-version conflicts, archival/reactivation, rename protection for referenced values, profile validation, import preview/commit staleness, and audit records. Migration rehearsal checks preservation and backfill. Chromium acceptance covers IT catalog creation, profile selectors, and Superuser visibility. Container CI asserts that `reference-data.js` is packaged in the production application image.
