# Audit workspace

The **Audit log** workspace is available to Superusers and IT Administrators. It shows the newest application audit events first and is read-only. Backend role checks protect `GET /api/v1/reports/audit`; hiding the navigation item is only a usability measure.

Each row shows the event time, current actor username and account ID, action, entity type and identifier, and the opaque request ID that links the event to the access log. Event details are disclosed only when the reader expands a row. Values are inserted as text, not interpreted as HTML. The view does not expose passwords, tokens, or student-profile values because those are excluded from the audit payloads.

The workspace loads 50 events at a time. Previous/next controls page through the result set. Action, entity type and actor ID filters are exact matches; clearing filters returns to the newest events. The API preserves its list response and supports `limit`, `offset`, `action`, `entity_type`, and `actor_id` query parameters. Requests remain bounded to 500 events per page.

The actor username is resolved from the current user account record; the stable actor ID remains visible if the account cannot be resolved. Legacy events without request correlation display a dash. Access logs contain the request ID, method, route template, status and duration; query strings, request bodies, credentials and exception messages are excluded. Events are not edited or deleted from this workspace.
