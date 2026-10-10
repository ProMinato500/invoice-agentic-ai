# API

Interactive typed request schemas and actual endpoint descriptions are available at `http://127.0.0.1:8010/docs`. All `/api` routes are scoped to the configured local workspace and optionally require `Authorization: Bearer <API_TOKEN>`.

- Documents: POST upload; GET list/details/original file/pages/page PNG/elements/lines.
- Reconciliations: POST create; GET paginated history/details/events/SSE/matches/discrepancies/reviews/report; POST retry/cancel/recalculate.
- Review: POST match review with optimistic version, action, optional PO line and required audit note.
- Extraction: GET element; POST canonical correction with evidence ID, line ID, field, value, version and required note.
- Investigation: POST discrepancy investigation executes an audited, authorized source-evidence lookup.
- Dashboard: GET summary/activity.
- Synthetic: GET scenarios; POST scenario load ingests only PDF bytes.
- Evaluation: POST benchmark; GET history/details.
- GET /health and /ready expose runtime state; GET /api/settings exposes non-secret configuration.

Pagination uses `limit` and `offset`. SSE supports `after` and Last-Event-ID, with persisted microsecond sequence identifiers. Reports use `?format=pdf|csv|json` and return conflict if the current result version has no report. Review/correction requests return 409 when stale or processing. Unauthorized record IDs return 404. Malformed PDFs, passwords and unreadable extraction return explicit errors.
