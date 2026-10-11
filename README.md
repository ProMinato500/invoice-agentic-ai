# ReconcileAI

**AI-assisted purchase order and invoice reconciliation, with inspectable source evidence and audited human review.**

ReconcileAI accepts real PDF documents, extracts their contents, maps invoice items to purchase-order items, and produces a reasoned result. The portal shows live processing stages, source highlights, discrepancies, saved reviews and downloadable reports.

This repository provides a **local, single-user application**. The frontend, API, worker, OCR, embedding encoder and persistence run locally. Generative AI requests use your configured Azure OpenAI or OpenAI provider. No Docker, Redis or PostgreSQL service is required.

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Using the portal](#using-the-portal)
- [Architecture and processing](#architecture-and-processing)
- [Repository structure](#repository-structure)
- [Testing and demo inputs](#testing-and-demo-inputs)
- [Troubleshooting](#troubleshooting)
- [Scope and limitations](#scope-and-limitations)
- [Further documentation](#further-documentation)

## What it does

- Extracts PDF layout and tables with **Docling**, using **RapidOCR** for scanned content.
- Retains table headers, cell positions, spans and source regions alongside canonical item fields.
- Retrieves PO candidates using identifiers, SQLite FTS5, fuzzy matching and local dense embeddings.
- Uses bounded AI roles for extraction recovery, product matching, specification assessment and exception investigation.
- Separates product correspondence, specification compliance, quantity allowance and price checks.
- Proposes capacity-compatible allocations with **OR-Tools** and validates financial values with **Decimal** arithmetic.
- Streams persisted workflow events through **SSE**, with clickable OCR, tool, solver and validation outputs.
- Saves human reviews and corrections immediately, then recomputes the saved batch through one explicit action.
- Generates versioned **PDF, CSV and JSON reports**, retaining original documents and prior artifacts.

## Quick start

### Prerequisites

| Requirement | Notes |
| --- | --- |
| Windows with PowerShell or Command Prompt | Included setup/start/stop scripts target Windows. |
| Python 3.13 | Version used by `setup-local.cmd` and verified for this project. |
| Node.js 24 and npm | Verified runtime. Node 20.9+ is the intended minimum, but other versions have not been validated here. |
| uv | Used by the automatic setup script; a pip-based alternative is below. |
| Network access | Needed for package/model downloads and generative AI calls. Models are cached after download. |
| Azure OpenAI or OpenAI access | Required to exercise the full AI workflow. Local embeddings do not require an API key. |

Clone or download this repository, open a terminal in its root directory, and run:

```powershell
.\setup-local.cmd
```

Setup creates `.venv`, installs locked Python and frontend dependencies, creates `.env` from `.env.example` if missing, applies migrations, generates fictional test PDFs, copies the PDF.js worker and builds the frontend. It preserves an existing `.env`.

Open `.env` privately and configure **one** generative AI provider as described below, then start the application:

```powershell
.\start-local.cmd
```

| Service | Default URL |
| --- | --- |
| Portal | http://127.0.0.1:3000 |
| API documentation | http://127.0.0.1:8010/docs |
| API health | http://127.0.0.1:8010/health |
| Runtime readiness | http://127.0.0.1:8010/ready |

The launcher starts the API, durable worker and frontend in background processes. Logs are written to `storage/logs/`. First-use model initialization can take several minutes, especially for scanned PDFs.

Stop the application with:

```powershell
.\stop-local.cmd
```

Stopping preserves the database and uploaded files. The launcher checks process identity before stopping its own services.

For frontend development, use:

```powershell
.\start-local.cmd --dev
```

### Manual setup without uv

Run from the repository root with Python 3.13 available:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m synthetic_data generate --all --seed 42
Set-Location frontend
npm.cmd ci --cache ..\.cache\npm
New-Item -ItemType Directory -Force public | Out-Null
Copy-Item -LiteralPath node_modules\pdfjs-dist\build\pdf.worker.min.mjs -Destination public\pdf.worker.min.mjs
npm.cmd run build
Set-Location ..
```

Configure your private `.env`, then run `start-local.cmd`. Use `npm.cmd` on Windows if PowerShell blocks `npm.ps1`.

## Configuration

[.env.example](.env.example) contains configuration names and safe defaults. All API keys, endpoints specific to your account, deployment names and tokens are blank. Put your own values only in `.env`; `.env` and other `.env.*` files are ignored by Git, while `.env.example` is retained.

### Choose one AI provider

| Provider | Fill in your private `.env` |
| --- | --- |
| OpenAI | `OPENAI_API_KEY`; set `OPENAI_MODEL` and `OPENAI_VISION_MODEL` to models available to your account. `OPENAI_BASE_URL` is optional. |
| Azure OpenAI | `INVOICE_AZURE_ENDPOINT`, `INVOICE_AZURE_API_KEY` and `INVOICE_AZURE_DEPLOYMENT`. Use your resource's base endpoint and actual deployment name. |

The Azure client appends `/openai/v1/` to the resource endpoint. Use a deployment supporting the application's Responses, structured-output and tool-calling workflow; source vision also requires image support. If both providers have credentials, the implementation selects OpenAI first.

With credentials unset, uploads, persistence and deterministic paths remain available, but ambiguous cases cannot use the full AI workflow and may require review. Credentials are read server-side, not passed to frontend environment variables.

### Main options

| Setting | Template default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./storage/reconcile.db` | Local application database. |
| `STORAGE_PATH` | `./storage` | Originals, cached models, checkpoints, logs and reports. |
| `PARSER` / `DOCLING_PIPELINE` | `docling` / `standard` | Layout, table and OCR extraction. |
| `ENABLE_EMBEDDINGS` | `true` | Enable dense candidate retrieval. |
| `EMBEDDING_PROVIDER` | `local` | Use the locally cached MiniLM encoder without a provider embedding key. |
| `DEFAULT_PRICE_TOLERANCE_PERCENT` | `2` | Initial unit-price tolerance; selectable when creating a run. |
| `ROUNDING_TOLERANCE` | `0.02` | Monetary rounding allowance used by validation. |
| `MAX_UPLOAD_MB` / `MAX_PAGES` | `50` / `500` | Input limits; these are not performance guarantees. |
| `MAX_AI_REQUESTS_PER_RUN` / `MAX_AGENT_TOOL_CALLS` | `48` / `24` | Bounds on model requests and dispatched tools. |
| `MAX_AI_TOKENS_PER_RUN` | `180000` | Consumed-token budget checked between requests, not a monetary spending cap. |
| `MAX_RECOVERY_PAGES` | `24` | Bounds source recovery work. |
| `API_PORT` / `FRONTEND_PORT` | `8010` / `3000` | Launcher ports. |
| `API_TOKEN` | Empty | Keep empty for the standard local portal; there is no login/token-entry UI. |

Local embeddings download `sentence-transformers/all-MiniLM-L6-v2` on first use and cache it under `storage/model-cache/embeddings/`. For provider embeddings, change `EMBEDDING_PROVIDER` to `provider` and configure an appropriate embedding model. Azure embeddings require `AZURE_EMBEDDING_DEPLOYMENT`; a chat deployment alone is insufficient.

Restart the application after backend configuration changes. If changing the frontend port, update `CORS_ORIGINS`. If changing the API port, rebuild the frontend with `RECONCILE_API_ORIGIN` set to the corresponding API URL so its `/api` rewrite targets the correct service.

## Using the portal

1. Open **New reconciliation** and upload a PO, one or more invoices, and optional supporting PDFs. The synthetic library can load fictional example documents through the same ingestion path.
2. Set the price tolerance and select **Start reconciliation**.
3. Follow the persisted execution timeline. Expand a stage and choose **View output** to inspect actual extraction, AI/tool, allocation or validation results.
4. Use **Inspect OCR & extraction** to browse OCR text, reconstructed tables, canonical rows and parser metadata. Clicking linked text or a cell highlights its source region.
5. Read the separate correspondence, specification, quantity and price statuses. Expand discrepancies; **Audit source lookup** opens available citations and explicitly identifies missing citation coverage.
6. Use **Inspect** to compare the invoice and PO. Save a mapping review, correction or documented authorization with a note.
7. Save all intended reviews first. They persist immediately and increment the pending-change count; saving does **not** queue a new run. Current report downloads are disabled while changes are pending.
8. Click **Recompute saved reviews** once. The batch creates one new result version and reruns checks. Shared-document corrections can mark several runs pending; recompute each affected run explicitly.
9. Download PDF, CSV or JSON reports after processing completes. Earlier trace/report artifacts and reviewer history are retained.

A quantity pass means the invoice fits the **remaining ordered allowance**, allowing partial billing; it does not prove delivery. Accepting a product correspondence does not automatically waive specification or financial failures. Discrepancies include both confirmed rule failures and missing evidence.

## Architecture and processing

```text
Next.js portal -> FastAPI -> SQLite queued run
                             |
                       Local worker + LangGraph
                             |
Extract -> Index -> Match -> Allocate -> Specifications -> Financial policy
   |                                                        |
Source recovery                              Exception investigation / revalidation
                             |
                      Versioned reports + result
                             |
                  Persisted events -> SSE -> portal
```

| Layer | Implementation |
| --- | --- |
| Portal | Next.js, React, TypeScript, React Query and PDF.js. |
| API / data | FastAPI, Pydantic, SQLAlchemy, Alembic and SQLite/WAL. |
| Workflow | A separate OS-locked local worker and LangGraph with SQLite checkpoints. |
| Extraction | Docling, RapidOCR, PyMuPDF source geometry and canonical normalization. |
| Retrieval | Identifiers, SQLite FTS5, RapidFuzz, MiniLM vectors and reciprocal-rank fusion. |
| AI | Four bounded roles with versioned prompts, scoped tools, typed outputs and source validation. |
| Decision checks | OR-Tools capacity proposals and Decimal-based financial/specification policy. |
| Observability | Persisted events, public trace payloads, SSE replay and reviewer audits. |

AI interprets evidence; numerical and approval policy remain explicit services. Only qualifying ordinary results commit billing allocations. Exception investigation cannot override financial failures. Original PDFs and raw parser readings remain preserved when human corrections change canonical fields.

## Repository structure

```text
backend/             FastAPI, extraction, agents, workflow and validation
  app/               Application modules
  migrations/        Alembic schema migrations
  tests/             Backend unit and integration tests
frontend/            Next.js portal and Playwright workflows
synthetic_data/      Fictional PDF generation and scenario manifests
evaluation/          Isolated synthetic benchmarks
scripts/             Local launcher, verification and demo-input utilities
docs/                API, architecture, data model and implementation notes
.env.example         Public configuration template with blank credentials
setup-local.cmd      Dependency installation, migrations and frontend build
start-local.cmd      Start the local services
stop-local.cmd       Stop only launcher-owned services
storage/             Generated runtime data; ignored by Git
```

## Testing and demo inputs

### Backend checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check backend synthetic_data evaluation scripts
```

Backend tests use isolated temporary databases rather than the normal workspace ledger. See [implementation status](docs/implementation-status.md) for recorded verification and its limits.

### Frontend build

```powershell
Set-Location frontend
npm.cmd run build
Set-Location ..
```

### Browser workflow checks

Start the application before running Playwright. Generate fresh browser fixtures from the root, then run:

```powershell
.\.venv\Scripts\python.exe scripts\browser_fixtures.py
Set-Location frontend
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '..\.cache\playwright'
npx.cmd playwright install chromium
npm.cmd run test:e2e
Set-Location ..
```

These workflows use the running services and may create persisted fictional runs. Tests exercising generative AI require working credentials and may incur provider usage. Model downloads and cold initialization can lengthen execution.

### Sample PDFs and evaluation

```powershell
.\.venv\Scripts\python.exe -m synthetic_data generate --all --seed 42
```

Generated inputs live under `synthetic_data/generated/`. Once an invoice has committed allocations, repeating it can correctly trigger duplicate or remaining-capacity findings. Use fresh identifiers for repeated live demos, or the isolated benchmark route at **http://127.0.0.1:3000/evaluation**. Evaluation is available directly but is not in the main sidebar. Ground truth is read after inference; synthetic results are not a guarantee for unseen PDFs.

For the case-study recording, show a **happy path and at least one edge case running live** within five minutes. Explain processing using the portal's timeline and outputs; the candidate guide asks for **no slides**.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing `.venv` or frontend build | Run `setup-local.cmd`, or use the manual setup steps. |
| Port already occupied | Stop your existing ReconcileAI launcher session or choose free ports. The launcher does not stop unrelated applications. |
| Slow first extraction | Model initialization/downloads can take minutes. Check `storage/logs/worker.log` and real timeline events. |
| AI not configured / request failure | Check your private provider settings, deployment capabilities, network access and API/worker logs. |
| Embeddings cannot download | Check network access and model cache. Disabling `ENABLE_EMBEDDINGS` removes the dense path; identifier/lexical/fuzzy retrieval remains. |
| Saving reviews does not start processing | Expected behavior: click **Recompute saved reviews** after completing the batch. |
| Report downloads disabled | Pending changes or unfinished processing prevent a fresh report from being available. |
| Duplicate / capacity finding on repeated demo | Previously qualifying invoices retain allocations. Use fresh demo identities or isolated evaluation. |
| Browser cannot reach API after a port change | Check `RECONCILE_API_ORIGIN`, rebuild the frontend and restart the launcher. |

Default-port health checks can also be run with:

```powershell
.\.venv\Scripts\python.exe scripts\verify_local.py
```

## Scope and limitations

- This is a local, single-user delivery; there is no account/login workflow or deployed multi-tenant service.
- Generative AI requires provider access. Cached local OCR/embeddings do not make generative inference offline.
- Unreadable, ambiguous or incomplete evidence remains reviewable; arbitrary unseen PDFs are not guaranteed to extract correctly.
- Supporting receipts, specifications and amendments are retained for inspection, but their policy effects are not automatically adopted.
- Arbitrary bundles, unsupported unit conversions, amendment precedence, goods-receipt approval, FX, credit notes and complex tax treatment require additional verification/policy work.
- Compatible-unit allocation proposals and reviewed splits exist; they are not universal bundle reconciliation.
- No payments are initiated. An auto-approvable result means the implemented checks passed, not proof of delivery or authorization to execute a payment.

## Further documentation

- [Architecture](docs/architecture.md)
- [Agent roles and tools](docs/agent-tools.md)
- [API reference](docs/api.md)
- [Data model](docs/data-model.md)
- [Synthetic data](docs/synthetic-data.md)
- [Testing](docs/testing.md)
- [Edge cases](docs/edge-cases.md)
- [Implementation status and recorded verification](docs/implementation-status.md)
