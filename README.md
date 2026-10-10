# ReconcileAI - local purchase order / invoice reconciliation

A local Next.js + FastAPI application that processes real PDF files, persists documents and results in SQLite, uses Docling with RapidOCR, and invokes your configured Azure/OpenAI model for uncertain layouts and product correspondence. Monetary calculations use Python Decimal. LangGraph checkpoints, workflow events and reviewer actions are persisted.

This implementation follows the supplied brief with the user's explicit **local-first** adjustment: no Docker, Redis, PostgreSQL server or deployment is required. The application is a single-user local workspace, not a deployed multi-tenant SaaS.

## Start on this machine

Dependencies and the production frontend have already been installed/built in this workspace.

```powershell
.\start-local.cmd
```

Open **http://127.0.0.1:3000**. API documentation is at **http://127.0.0.1:8010/docs**. Port 8010 avoids the existing application on port 8000. The launcher starts the API, durable local worker and frontend in hidden processes. Logs are in `storage/logs/`.

```powershell
.\stop-local.cmd
```

The stop command verifies executable arguments, workspace directory, PID and process creation time. It stops only processes started by this launcher. No database or uploaded document is deleted. To use development mode, run `start-local.cmd --dev`.

## Fresh setup

Python 3.13 (the version verified here), Node.js 24 and uv are required. Python 3.12+ and Node 20.9+ are the intended minimums, but other combinations have not been verified.

```powershell
.\setup-local.cmd
.\start-local.cmd
```

Setup creates `.venv`, installs the resolved Python dependency lock, runs non-destructive Alembic migrations, generates real test PDFs, installs frontend dependencies from `package-lock.json`, copies the matching PDF.js worker and builds Next.js. It does not overwrite an existing `.env`.

Manual setup is available if uv is unavailable:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m synthetic_data generate --all --seed 42
cd frontend
npm.cmd ci --cache ..\.cache\npm
New-Item -ItemType Directory -Force public
Copy-Item node_modules\pdfjs-dist\build\pdf.worker.min.mjs public\pdf.worker.min.mjs
npm.cmd run build
cd ..
.\start-local.cmd
```

Use `npm.cmd` on Windows to avoid blocked `npm.ps1` execution policies. The `.cmd` launchers do not require changing PowerShell execution policy.

## Workflow

1. Select **New reconciliation** and upload a PO, one or more invoices and optional supporting PDFs, or load PDFs from the synthetic library.
2. Set the deterministic unit-price tolerance and start reconciliation.
3. Follow real extraction/indexing/matching/validation/report events. First use initializes Docling's CPU models; scanned pages take longer than native PDFs.
4. Inspect the paginated line results. Correspondence, specification, quantity and price are independent statuses.
5. Open **Inspect** to view the original PDFs with actual extracted source rectangles. Review a mapping, choose an alternative, mark unmatched, document an authorized substitution, or correct a canonical extraction field.
6. Saving a review writes an audit event, versions the result and queues recomputation. A substitution never bypasses price, total or quantity checks.
7. Download real PDF, CSV and JSON reports. Run history and corrections persist after restart.
8. Execute a synthetic benchmark in **Evaluation**. Ground truth is loaded only after each inference run finishes. Benchmark allocations are isolated from the normal billing ledger.

A full invoice already allocated against a PO will make later invoices exceed remaining capacity. Loading another synthetic scenario against the same PO does not reset the ledger. Use **Evaluation** for isolated scenario comparison.

## Configuration

Existing `INVOICE_AZURE_ENDPOINT`, `INVOICE_AZURE_API_KEY` and `INVOICE_AZURE_DEPLOYMENT` are supported through the official OpenAI SDK and Azure's v1 Responses endpoint. Alternatively set `OPENAI_API_KEY` and `OPENAI_MODEL`. Credentials stay on the server and are excluded from source control. Missing credentials are disclosed; ambiguous items remain review-required.

`PARSER=docling` and `DOCLING_PIPELINE=standard` select the full layout/table/OCR pipeline. `PARSER=pymupdf` is an explicitly labeled native PDF parser option used for deterministic offline integration tests; it is not silently substituted for Docling. The local application uses Docling by default.

The local matcher uses exact identifiers, SQLite FTS5 lexical retrieval, RapidFuzz and reciprocal-rank fusion. Optional OpenAI embeddings are stored as provenance-bearing vectors and compared exactly in the same SQLite-backed application; no additional vector database is used. Embeddings are **disabled by default** because an Azure chat deployment is not an embedding deployment. To enable them, supply an OpenAI key and set `ENABLE_EMBEDDINGS=true`. The embedding path has not been live-verified in this session.

Set `API_PORT` / `FRONTEND_PORT` if ports are occupied. Rebuild after changing frontend routing configuration. If changing the frontend port, update `CORS_ORIGINS`. `API_TOKEN` optionally enables bearer-token authentication; enter that token under **Settings** for the current browser session. Bindings remain loopback-only.

## Synthetic PDFs and tests

```powershell
.venv\Scripts\python.exe -m synthetic_data generate --all --seed 42
.venv\Scripts\python.exe -m synthetic_data generate --scenario specification_mismatch --seed 42
.venv\Scripts\python.exe -m synthetic_data generate --scenario large_document --po-lines 5000 --invoice-lines 3000 --seed 42
.venv\Scripts\python.exe -m pytest -q
cd frontend
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '..\.cache\playwright'
npx.cmd playwright install chromium
cd ..
.venv\Scripts\python.exe scripts\browser_fixtures.py
cd frontend
npm.cmd run test:e2e
```

The browser test needs the running API/worker/frontend. It creates unique fictional PDF inputs, uploads them, checks SSE replay, displays evidence, approves a documented synthetic substitution, recomputes, downloads reports and refreshes history. Unit/integration tests create isolated temporary databases and do not alter workspace data. See `docs/implementation-status.md` for actual verified results and limitations.

## Boundaries

The full research brief is broader than this local implementation. Unverified equivalence is never assumed. Complex bundles/split allocations, automated amendment precedence, goods-receipt approval, inclusive/mixed-tax interpretation, authorized FX, cancellation/revision policies, conditional/certification standards, learned ranking, all corruption variants and 5000-line performance gates are not certified. Supporting PDFs are retained for human inspection and trigger review rather than silently authorizing changed terms. The current generated product catalog focuses on IT configurations; template names do not certify domain coverage.

No payment is initiated. No arbitrary shell, file path or SQL tool is exposed to the AI. This is a functioning local review application, not a claim of universal extraction accuracy or production SaaS readiness.

## Inspect execution during a demo

See [demo guide](docs/demo-guide.md). Expand a run stage and click **View output** for OCR, AI/tool decisions, allocation or validation results. **Inspect OCR & extraction** opens source text beside the PDF. Page vision reinspection and reviewer verification create audited result versions.
