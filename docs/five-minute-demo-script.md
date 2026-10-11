# ReconcileAI: five-minute presentation and portal demo

## Presentation format

Use a two-slide PPT: a title slide and one architecture slide. Build the architecture in draw.io using `reconcileai-architecture.drawio`, export it as SVG or PNG, and insert it into the architecture slide. Present the slide rather than the draw.io editor; switch to the browser after the architecture explanation. Keep the editable draw.io file for technical questions.

The diagram separates the runtime components from the processing workflow. Blue boxes are application/workflow components; purple is the external AI provider; amber marks conditional recovery/investigation; storage holds persistent state and artifacts. Generative AI calls use the configured Azure/OpenAI provider; this is not an entirely offline application.

## Before presenting

- Start the portal and worker in advance. Open Overview, New reconciliation, a completed run with a visible discrepancy, and a completed reviewed run with reports in separate browser tabs.
- Prepare a PO and invoice that you can explain. For repeat demonstrations, use fresh synthetic PDFs with unique invoice/PO identifiers (`.venv\Scripts\python.exe scripts/browser_fixtures.py`). Reusing an already allocated invoice can correctly trigger duplicate and remaining-capacity checks.
- Warm the parser by processing the demo documents beforehand. Do not rely on a cold OCR/AI run finishing within five minutes. Show a fresh run's progress, then explicitly switch to a previously completed run for results.
- Identify one table cell, one matched item, one finding with linked evidence, and one review action before presenting. Keep an unreviewed sample for the live save step.
- If an item has a genuine specification difference, accepting its product correspondence does not waive that difference. Use an authorized substitution only when your demo note cites the fictional authorization. Never suggest that review bypasses financial checks.

## Spoken script and screen cues

The script below is approximately 680 words. Rehearse at a comfortable pace; the five-minute allocation includes clicks and brief pauses.

### 0:00-0:25 - Purpose | Title slide, then Overview

"ReconcileAI compares purchase orders with invoices and explains the result using the original documents. It answers four separate questions: is this the same product, are the specifications compliant, is the quantity within the order's remaining allowance, and is the price acceptable? The dashboard shows actual saved runs and documents. The goal is to help a reviewer reach an evidence-backed decision."

### 0:25-1:15 - Architecture | Show the architecture slide

?The frontend is Next.js with TypeScript. It calls a FastAPI backend for uploads, reconciliation results, reviews and reports. Original PDFs and generated artifacts are stored as files; SQLite stores document metadata, normalized items, results, allocations, events and audit records. LangGraph checkpoints are also persisted in SQLite.

?Long-running work happens in a separate worker, which claims queued database jobs. An operating-system lock prevents a second worker from claiming work. LangGraph controls the stages and conditional branches. The browser receives progress through server-sent events, or SSE, and retrieves saved outputs when I open a stage.

"This is the implemented local architecture. It does not require Redis, Docker or a separate vector database. AI calls go to the configured provider, with credentials kept on the server."

### 1:15-1:40 - Create a run | New reconciliation

*[Upload the PO and invoice, briefly point to supporting PDFs and the price tolerance, then select Start reconciliation.]*

"I upload the purchase order and invoice, with optional supporting PDFs. The backend validates the PDF, enforces configured limits, hashes the file for deduplication, and preserves the original. Starting reconciliation creates a queued run. Here we can see real stage progress. While this processes, I will open a completed run to show the outputs."

### 1:40-2:20 - Extraction | Completed run > Inspect OCR & extraction > Tables

?Docling extracts document layout and tables, using RapidOCR for scanned content. The parser retains cells, headers, row and column spans, page numbers and source rectangles. This context helps keep values associated with the right headers. Extracted fields become canonical items such as SKU, description, quantity, unit price and amount.

"Quality checks look for incomplete or unclear extraction. The extraction-recovery AI role can inspect source evidence and propose structured, field-cited readings. Targeted vision reinspection is available for uncertain pages. Alternative readings remain visible rather than silently replacing verified values."

*[Click a table cell to highlight its original PDF region.]*

### 2:20-3:05 - Agentic matching | Timeline > Matching > View output; then line results

?Candidate retrieval combines exact identifiers, lexical search, fuzzy matching and local embeddings, with rankings fused together. AI-generated aliases help retrieval but are not authoritative product facts.

"There are four bounded AI roles: extraction recovery, product matching, specification assessment and exception investigation. They use scoped tools to inspect evidence or search candidates, then return schema-constrained output. Product matching requires evidence from both the invoice and selected PO item. The specification role assesses printed attributes separately. We can inspect saved tool calls, structured decisions and citations here. This is public execution evidence, not private chain-of-thought."

### 3:05-3:40 - Allocation and checks | Point to Quantity, Price, Specifications; expand a finding

?OR-Tools proposes allocations across candidate matches while respecting remaining PO capacity. Decimal arithmetic then checks quantities, prices, line amounts and totals. Other rules check document references, parties, currencies and duplicates. Only qualifying results commit allocations to the ledger.

"For example, an invoice for 35 units against an available allowance of 60 can pass quantity because partial invoicing is allowed. That does not prove delivery. Missing specifications remain unverified. An exception agent can investigate findings, but it cannot override financial rules."

### 3:40-4:25 - Human review and traceability | Audit source lookup > Inspect > Save review

?Discrepancies include failed checks and missing information. Audit source lookup opens the cited documents; it does not resolve the finding itself. Inspect lets me compare both originals and save a mapping review or extraction correction with a note.

"I can save several reviews first. They persist with an audit trail, and this banner counts pending changes. The displayed checks still belong to the previous computation, so report downloads are disabled. Recompute saved reviews applies the batch in one new result version and reruns the checks. Earlier traces, reports and original source files remain preserved."

*[Save one review. Point to the pending banner. Click Recompute saved reviews; use the already reviewed tab for the next segment if processing is still active.]*

### 4:25-5:00 - Reports and close | Reviewed run > audit trail, previous versions, PDF report

?This completed run shows the reviewed result and its audit history. I can inspect earlier versions and download PDF, CSV or JSON reports containing the result, findings, evidence and review annotations. Refreshing the page preserves the history because it is stored in the backend.

"AI handles interpretation and uncertain correspondence; explicit rules enforce financial correctness; human review handles unresolved evidence. ReconcileAI does not initiate payments or guarantee perfect extraction of every PDF. It makes uncertainty visible and gives the reviewer a traceable path from source document to decision."

## Answers to likely architecture questions

| Question | Answer |
| --- | --- |
| What makes it agentic? | Four bounded reasoning roles execute real allowlisted tool calls, inspect scoped evidence, search or investigate, and return validated structured decisions. LangGraph also has conditional source-reinspection and exception branches. |
| Is everything controlled by an LLM? | No. AI interpretation is combined with deterministic extraction checks, source-ID validation, OR-Tools capacity planning, Decimal financial checks and approval policy. |
| How are tables understood? | Saved grids retain headers, spans, row/column positions and source evidence. Canonical extraction and recovery use that context; ambiguous mappings remain reviewable. |
| Where are embeddings stored? | SQLite-backed vectors, using the local MiniLM encoder in the current setup; exact cosine ranking is fused with lexical/fuzzy retrieval. No pgvector server is needed. |
| What happens if the worker restarts? | Persisted queued/abandoned work can be reclaimed; checkpoints and result-version guards support recovery. This does not guarantee external provider calls run exactly once. |
| Does SSE contain all OCR output? | It carries progress and references to persisted events. The UI requests the saved payload when opening an output. |
| Does Save review immediately run AI again? | No. It persists the change and audit record. One explicit recompute creates the next result version for the saved batch. |
| Is supporting-document policy automated? | Supporting PDFs are available as evidence. Receipt approval, amendment precedence and unsupported policy effects still need verification. |
| What does "auto approvable" mean? | The implemented policy checks passed. It is not a payment instruction or proof that goods were delivered. |

## Accurate claims

Do not present PostgreSQL/Redis/Celery as part of this runtime, claim that all models run offline, describe every discrepancy as a confirmed invoice error, or turn synthetic benchmark results into an accuracy guarantee for unseen PDFs. Do not show credentials or raw .env contents during the demo.
