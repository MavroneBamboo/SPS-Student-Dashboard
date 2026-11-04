# Student reference catalogs

## Purpose

IT Administrators and the Superuser can maintain category, institution, and academic-year labels from **Reference data**. The API is under `/api/v1/student-reference/catalogs/` with `categories`, `institutions`, and `academic-years` resources. Operators and Executives may read active values; only IT Administrators and the Superuser may create, rename, archive, or reactivate them.

Catalog labels are normalized with Unicode NFKC, collapsed whitespace, and case folding for uniqueness. Updates carry an expected version and use a compare-and-swap write; stale edits return 409. Changes are audited. Values are archived rather than deleted, preserving identifiers and history. Academic-year values can optionally carry effective dates. The migration backfills distinct existing student categories and academic years found in students and timetable configuration without changing those source records. Institution values begin empty because the current student model and supplied import path do not yet record a student institution.

## Current boundary

This increment provides catalog administration and data preservation. It does not yet make catalogs authoritative for profile entry or import validation: student category and academic year fields remain strings, and institution is not yet a student field. The next profile integration increment must add the institution relationship, change the browser profile controls to controlled values, validate profile writes server-side, and bind import preview and commit to active catalog values with stale-version checks. Existing profile values must remain readable and be reconciled explicitly before any hard foreign-key conversion.

## Verification

API coverage checks role access, Unicode/case/whitespace duplicate handling, date validation, expected-version conflicts, archival/reactivation, and audit records. Migration rehearsal checks preservation and backfill. Chromium acceptance covers IT catalog creation and Superuser visibility. Container CI asserts that `reference-data.js` is packaged in the production application image.
