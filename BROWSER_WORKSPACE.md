# Production browser workspace increment

The attendance increment adds the Operator **Attendance** screen for real daily sessions, records/corrections, count controls, missing review and closure. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md), including version contracts and the current-profile eligibility boundary. Timetable/resource screens, full intake/import/export and deployment hardening remain outstanding.

The subsequent profile increment adds the Operator **Student profiles** screen, with paged search, create/edit, status history and version-checked saves. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md). Earlier delivery boundaries below describe the initial shell; attendance/resource/timetable browser screens, full intake schema and permission hardening remain outstanding.

Start the Compose stack using the configured deployment secrets, then open `http://localhost:8080/` (redirects to `/ui/`). The approved synthetic prototype remains separately available at `/prototype/index.html`. The root now opens the actual application, with no prototype fallback. Deployments must supply approved HTTPS termination before operational use; the current development Compose listener remains HTTP.

## Delivered workflow

Sign in using the configured bootstrap or a named application account. Accounts marked for password change must enter their current password and a matching new password of at least 12 characters before reaching the workspace. Invalid credentials and server validation errors appear in the page. No initial password is embedded in the assets.

The Superuser opens account administration: create a named account, choose its role and supply a temporary password; the new account must rotate that password on first login. Existing accounts can have their role or active status changed. Backend checks protect self-disablement and the last active Superuser. Temporary password fields are cleared after submission. The browser does not display password hashes or repeat temporary passwords in success messages.

IT Administrator, Operator and Executive accounts open the committed-data dashboard. It shows current active students, attendance rate (present/late divided by expected), missing records, session totals, class/category breakdowns and individual attendance session rows. Class filters affect profiles and attendance; date filters affect attendance only. Apply filters or refresh after manual updates to load committed data, with a server refresh timestamp. No sample figures are used. Overlapping dashboard requests cannot overwrite a newer filter result with an older response.

The first browser increment does not include profile/attendance entry forms, resource editors, timetable/Amend 4-up screens, imports, print/export controls or the setup-completion/recovery wizard. Those remain required production work. User-management permissions currently remain Superuser-only in the backend; the broader IT Administrator account-management permission from the product design remains to implement. UI visibility never grants API access.

## Session and delivery controls

The client uses same-origin API requests and keeps its bearer access token only in module memory. It stores no credentials/tokens in cookies, localStorage or sessionStorage. Refreshing or leaving the page requires sign-in again. Expiry, explicit sign-out and authenticated 401 responses abort in-flight requests and clear sensitive workspace DOM and form values. Late responses from an older session cannot repopulate the page. Signing out clears the browser token; server-side session revocation and broader identity hardening remain future work, and an already issued token expires according to the backend policy.

`GET /api/v1/auth/me` returns the current database-backed ID, username, role and password-change flag, including while rotation is required. It confers no bypass of protected operation checks. The client does not trust editable JWT role claims to grant access. Deactivated users fail the backend's next authenticated request.

HTML/CSS/JavaScript are bundled in the application image and Python package. They require no CDN, public fonts, Node runtime or internet at runtime. Assets and API responses receive no-store and restrictive CSP/clickjacking/content-type/referrer headers. Dynamic values are rendered as text or DOM properties rather than HTML. Nginx routes the production app to FastAPI while retaining the explicit prototype path.

## Verification and remaining release gates

CI adds real Chromium tests against a live Uvicorn/API server and the disposable PostgreSQL database. These cover invalid login, mandatory rotation and confirmation, account creation/role edit/disable, all three operational role landings, filtered committed-data refresh, safe text rendering, sign-out/reload data clearing, expiry and account disablement. Screenshots contain only synthetic test data and are uploaded as CI artifacts; no traces or operational credentials are collected. Browser binaries are CI tooling, not runtime dependencies in the production image. The setup follows the [official Playwright Python library instructions](https://playwright.dev/python/docs/library).

API tests cover local asset delivery/security headers/traversal rejection and current identity state without rotation bypass. The production image check verifies all browser assets exist; CI checks Nginx configuration. Existing API, migration, audit, security, secret and container checks remain required. Full HTTPS Compose browser acceptance, deployment recovery, accessibility audit, browser compatibility beyond Chromium, production-scale tests and the remaining functional modules are still release gates.
