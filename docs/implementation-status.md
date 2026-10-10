# Implementation status - verified 11 October 2026

Scope: the user explicitly requested local-first running and deferred Docker, Redis and deployment. The shipped runtime is a local single-user application with SQLite/WAL, a durable OS-locked worker and SQLite LangGraph checkpoints. PostgreSQL/pgvector/Redis/Celery production deployment from the original brief is not the active local design.

## Implemented and verified

- Next.js App Router / TypeScript enterprise UI: Overview, New reconciliation, Runs, Review queue, Documents, Evaluation, Settings.
- Real PDF validation/upload, secure UUID storage, SHA256 deduplication, originals, persisted metadata and history.
- Actual Docling standard layout/table extraction and RapidOCR/ONNX full-scan processing; raw structured output and real source rectangles retained.
- Canonical line extraction, completeness gates, field-grounded chunked recovery, exact-ID matching, SQLite FTS5 + local dense vectors + RapidFuzz/RRF scoped retrieval and separately evaluated product/specification decisions.
- Live Azure gpt-4o Structured Outputs and real allowlisted function calling with four reasoning roles, per-run persisted budgets, bilateral candidate evidence checks and source-grounded specification proposals. Provider credentials preserved server-side.
- Decimal quantity/price/extended amount/subtotal/total checks, currency/supplier/buyer/PO reference checks, duplicate detection, partial and cumulative quantity accounting, PO source/revision checks and conservative discount/freight/tax safeguards.
- Transactional capacity accounting; review/blocked/evaluation runs do not consume normal billed quantities. Cancellation/failure releases this run's capacity.
- Real durable stage events and SSE replay (including terminal history draining), saved public request/tool/OCR/decision/solver/validation traces, clickable UI output/source inspection, guarded local worker startup/recovery and queued retry/cancellation/recalculation.
- PDF.js originals and tested cell-aligned highlights, reviewer mapping/alternate/unmatched/substitution actions, versioned canonical corrections, immutable raw evidence, dependent recomputation, search-index refresh and audit history.
- Actual versioned PDF/CSV/JSON reports with document identity, outcome, line data, discrepancies, evidence and reviewer annotations.
- Synthetic PDF factory: 15 scenario folders plus 12 layout-variant folders, fictional identities, invariant reproducible PDF generation and isolated ground truth. Stress-size CLI available.
- Synthetic evaluation executes the real pipeline and reads truth afterwards; benchmark capacity is isolated. New evaluations preserve ground-truth hashes/snapshots and progress.
- Non-destructive Alembic schema migration, reproducible dependency locks, Windows setup/start/stop scripts, hidden processes, PID/cwd/creation-time checks and local logs.

## Actual checks

| Check | Command / evidence | Result |
| --- | --- | --- |
| Schema | `.venv\Scripts\python.exe -m alembic current` | `0001 (head)` |
| Backend | `.venv\Scripts\python.exe -m pytest -q --tb=short` | **50 passed**, final run 38.62s |
| Python quality | `python -m ruff check backend synthetic_data evaluation scripts` | All checks passed |
| Frontend | `npm.cmd run build` | Production build + TypeScript passed; all 7 navigation routes and dynamic run route generated |
| Browser workflow | `npm.cmd run test:e2e` | **2 passed**, final suite 1.7m; real uploads, active SSE chunks, timeline/results, PDF pixels/evidence, reviewer recompute, PDF/CSV/JSON downloads, OCR trace inspection/download, raw parser output, refresh and navigation |
| Final visual QA | `node tests/visual-check.cjs` | Dashboard chart, desktop/mobile layout and persisted PDF evidence verified; no page errors |
| Live AI | configured Azure gpt-4o Responses/Structured Outputs | Real schema-valid response and actual semantic reconciliation events |
| Docling native PDF | actual generated purchase order | 1 structured table, 17 text elements |
| OCR | actual rasterized PO + invoice | 3 lines extracted/matched, AUTO_APPROVABLE; first full scan scenario 91.356s |
| Live benchmark | `70fff055-427f-4d3e-852b-c1c38a5649b4` | 15/15 expected policy outcomes; **0 false approvals**; real scanned/multi-page/extra/ambiguous/financial scenarios |
| Fresh corrected-truth benchmark | `cc1eea02-84c5-42f1-a70d-e7e9bbf06249` | semantic alias + scanned + happy path: F1=1, candidate Recall@5=1, 0 false approvals |
| Larger input | 100 PO / 60 invoice lines | Actual full workflow 112.344s; 60/60 correspondence, no false approval |
| Runtime | `python scripts/verify_local.py` | API, SQLite, local worker, Docling configuration and Azure configuration healthy |
| Restart | stop/start launcher + reopened persisted results | History, audit and downloads preserved; unrelated port-8000 app left running |

The first benchmark contained an incorrect semantic-alias correspondence label; its original measurements are retained with an explicit metadata note. The generator label was fixed and a new live benchmark was run rather than fabricating an improved result. Benchmark JSON is retained under evaluation/results; UI metrics are clearly synthetic benchmarks, not unseen-document accuracy claims. Cached extraction affects follow-up runtimes and is not represented as a fresh OCR timing.

## Explicit limits / unfinished parts of the broader brief

- Public SaaS tenancy, accounts, PostgreSQL/pgvector, Redis/Celery, Docker and deployment were deferred for this local delivery.
- Dense retrieval is now enabled using a downloaded, verified local all-MiniLM-L6-v2 model. This is an explicit local-first substitution for OpenAI embeddings; provider embeddings require a separately configured embedding deployment.
- Generative PO aliases and model-driven invoice search expansion are implemented with non-authoritative provenance. Learned LightGBM training, HNSW benchmarking and feedback-trained models remain absent; the brief makes learned ranking optional after sufficient labels.
- OR-Tools global capacity planning and reviewed compatible-unit splits are implemented. Arbitrary component bundles, packaging conversions and unsupported grouping semantics still require policy/source verification and are not silently allocated.
- Four bounded roles, actual tool dispatch, targeted source-page/crop vision readings, correction proposals and conditional exception/reinspection graph branches are implemented. The entire research brief's external-standard/receipt/amendment policy integrations are not certified; unknowns remain reviewable. Private reasoning is not displayed.
- Goods receipts, amendments and external specifications are stored for human inspection; their policy effects are not automatically adopted. Nonzero freight, unknown taxes, FX, credit notes, unsupported packaging conversions and conflicting revisions require review.
- All domain catalogs, conditional/certification/standard equivalence, all corruption variants, all operational fault-injection tests and the 5000/3000 performance gate remain unverified. The current catalog primarily covers IT configurations.
- The local UI does not certify every arbitrary unseen PDF. Unreadable/unsupported extraction explicitly fails or requires review; absent evidence never becomes a fabricated match.
- First Docling initialization after a worker restart can take several minutes on this machine; loaded-model/cached-document runs are faster. The app is not labeled production-ready solely because it starts.

## Local use

Open http://127.0.0.1:3000. API docs: http://127.0.0.1:8010/docs.

Use `start-local.cmd` and `stop-local.cmd`; fresh setup uses `setup-local.cmd`. Logs: storage/logs. Originals, database, checkpoints and versioned reports remain in storage. No user database was dropped or overwritten, and existing .env credentials remain intact. See README.md for exact manual commands and configuration.

## AI architecture audit

See [AI and agentic integration audit](ai-integration-audit.md) for the original-brief comparison, fresh provider check, complex-PDF accuracy limits and remaining implementation changes. The historical audit is retained; current role-based tool calling and output tracing are described in [agent tools](agent-tools.md) and the [demo guide](demo-guide.md).

## Follow-up agentic implementation verification

- Backend: 50 tests passed, including actual dispatcher-loop mocks, invalid tools/citations, completeness gates, numeric source checks, vision-not-independent safeguards, durable budgets, cross-run trace authorization, full terminal SSE replay, reviewed split ledger commitment, extraction verification and guarded human-interrupt resume.
- Frontend production build and TypeScript passed after adding the trace/recovery/verification UI.
- Live Azure function-calling smoke test: the model selected get_source_evidence, executed the real callable and returned a schema-valid supported assessment.
- Local embedding smoke test: actual 384-dimensional normalized vectors, related laptop/notebook similarity 0.688 versus unrelated pump similarity 0.044. Model cached in storage/model-cache/embeddings.
- Browser trace acceptance passed (including actual dark PDF pixels and rendering completion): saved output, OCR text selection, original PDF source highlight, raw Docling extraction, download and reload. A screenshot was saved to storage/browser-ocr-trace.png.
- A live unruled-layout attempt exposed noncanonical field naming. Its failure history is retained; the schema was constrained to canonical names and a regression test added. The corrected live worker/recovery/vision suite passed and is retained in storage/live-agentic-acceptance.json; prior 15-scenario measurements describe the earlier implementation and are not relabeled as new results.

See [demo guide](demo-guide.md) for exactly where to click. New traces are immutable files scoped to their run/event/version, with compact SSE references; historical events have an explicit fallback notice.

Final live acceptance: semantic_alias run 1025d972-b075-406b-89e9-3ab340b83973 executed matching/specification/exception tools; unfamiliar-layout run f7e15563-8f2c-4da6-a64f-e5018b3ee5fe extracted one real canonical row with recovery/specification/exception tools, and version 2 emitted an actual VISION_RESULT. Outcomes remained REVIEW_REQUIRED for source/specification uncertainty. These results establish real integration, not universal extraction accuracy.

Final live browser review run 258b2eec-66fd-426c-90fb-6cdbf4acacc9 completed at version 2 after a documented synthetic substitution. Backend/database/worker returned healthy checks, embeddings were enabled and no jobs remained active. The one failed pre-fix recovery attempt remains in history for audit; it was not deleted or reported as a successful case.

The SSE follow-up also fixed intermediate-outcome presentation: PROCESSING/QUEUED stays visible until the run settles. A dedicated uncompressed streaming route plus durable backend polling keeps timeline, line results and findings current during model investigations. Event sequence allocation is serialized locally to preserve replay ordering across writers.
