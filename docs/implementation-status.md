# Implementation status - verified 11 October 2026

Scope: the user explicitly requested local-first running and deferred Docker, Redis and deployment. The shipped runtime is a local single-user application with SQLite/WAL, a durable OS-locked worker and SQLite LangGraph checkpoints. PostgreSQL/pgvector/Redis/Celery production deployment from the original brief is not the active local design.

## Implemented and verified

- Next.js App Router / TypeScript enterprise UI: Overview, New reconciliation, Runs, Review queue, Documents, Evaluation, Settings.
- Real PDF validation/upload, secure UUID storage, SHA256 deduplication, originals, persisted metadata and history.
- Actual Docling standard layout/table extraction and RapidOCR/ONNX full-scan processing; raw structured output and real source rectangles retained.
- Canonical line extraction, exact-ID matching, SQLite FTS5 + RapidFuzz/RRF scoped retrieval, separately evaluated product/specification decisions.
- Live configured Azure gpt-4o Structured Outputs through the official SDK/Responses API, including semantic candidate verification. Provider credentials preserved server-side.
- Decimal quantity/price/extended amount/subtotal/total checks, currency/supplier/buyer/PO reference checks, duplicate detection, partial and cumulative quantity accounting, PO source/revision checks and conservative discount/freight/tax safeguards.
- Transactional capacity accounting; review/blocked/evaluation runs do not consume normal billed quantities. Cancellation/failure releases this run's capacity.
- Real durable stage events and SSE replay, source lookup audit, guarded local worker startup/recovery, queued retry/cancellation/recalculation.
- PDF.js originals and tested cell-aligned highlights, reviewer mapping/alternate/unmatched/substitution actions, versioned canonical corrections, immutable raw evidence, dependent recomputation, search-index refresh and audit history.
- Actual versioned PDF/CSV/JSON reports with document identity, outcome, line data, discrepancies, evidence and reviewer annotations.
- Synthetic PDF factory: 15 scenario folders plus 12 layout-variant folders, fictional identities, invariant reproducible PDF generation and isolated ground truth. Stress-size CLI available.
- Synthetic evaluation executes the real pipeline and reads truth afterwards; benchmark capacity is isolated. New evaluations preserve ground-truth hashes/snapshots and progress.
- Non-destructive Alembic schema migration, reproducible dependency locks, Windows setup/start/stop scripts, hidden processes, PID/cwd/creation-time checks and local logs.

## Actual checks

| Check | Command / evidence | Result |
| --- | --- | --- |
| Schema | `.venv\Scripts\python.exe -m alembic current` | `0001 (head)` |
| Backend | `.venv\Scripts\python.exe -m pytest -q --tb=short` | **35 passed**, final run 37.24s |
| Python quality | `python -m ruff check backend synthetic_data evaluation scripts` | All checks passed |
| Frontend | `npm.cmd run build` | Production build + TypeScript passed; all 7 navigation routes and dynamic run route generated |
| Browser workflow | `npm.cmd run test:e2e` | **1 passed**; real uploads, SSE replay, PDF pixels/evidence, reviewer recompute, PDF/CSV/JSON downloads, refresh and navigation; final full flow 4.3m including cold Docling startup |
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
- OpenAI embeddings have a real optional local exact-cosine path, but are disabled and not live-verified because no embedding deployment/key was configured.
- Generative dual augmentation, learned LightGBM ranking/training, HNSW recall benchmarking and feedback-trained models are not deployed. Current aliases are labeled deterministic vocabulary normalization.
- Complex split/bundle allocations and OR-Tools global assignment are not implemented. Ambiguous identifier/capacity mappings abstain for review.
- Full four-role autonomous recovery/tool-calling graph, targeted OpenAI vision recovery and the complete tool list from the brief are not implemented. Current structured calls and audited source tools are real and bounded; no private reasoning or fake tool calls are displayed.
- Goods receipts, amendments and external specifications are stored for human inspection; their policy effects are not automatically adopted. Nonzero freight, unknown taxes, FX, credit notes, unsupported packaging conversions and conflicting revisions require review.
- All domain catalogs, conditional/certification/standard equivalence, all corruption variants, all operational fault-injection tests and the 5000/3000 performance gate remain unverified. The current catalog primarily covers IT configurations.
- The local UI does not certify every arbitrary unseen PDF. Unreadable/unsupported extraction explicitly fails or requires review; absent evidence never becomes a fabricated match.
- First Docling initialization after a worker restart can take several minutes on this machine; loaded-model/cached-document runs are faster. The app is not labeled production-ready solely because it starts.

## Local use

Open http://127.0.0.1:3000. API docs: http://127.0.0.1:8010/docs.

Use `start-local.cmd` and `stop-local.cmd`; fresh setup uses `setup-local.cmd`. Logs: storage/logs. Originals, database, checkpoints and versioned reports remain in storage. No user database was dropped or overwritten, and existing .env credentials remain intact. See README.md for exact manual commands and configuration.

## AI architecture audit

See [AI and agentic integration audit](ai-integration-audit.md) for the original-brief comparison, fresh provider check, complex-PDF accuracy limits and remaining implementation changes. The current application is a hybrid pipeline with selective structured AI, not the complete four-role tool-calling architecture.
