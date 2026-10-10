# AI and agentic integration audit

Audited 11 October 2026 against docs/build-specification.md and the running local application. This is an implementation audit, not a certification of unseen-document accuracy.

## Verdict

The application has real Azure OpenAI Structured Outputs integrated into an otherwise largely deterministic reconciliation pipeline. It is not yet the complete four-role agentic design requested in the original brief. The local-first infrastructure substitutions were authorized by the user; the missing reasoning/recovery features are implementation gaps, not consequences of using SQLite.

Deterministic arithmetic, authorization, duplicate checks, allocation accounting and report generation are required by the brief (section 13). Making these LLM decisions would undermine financial correctness. AI should handle uncertain extraction, interpretation, candidate verification and bounded exception investigation.

## Connections and executed evidence

- Fresh runtime checks: API /health and /ready returned 200; SQLite connected, worker available, Docling standard parser configured, Azure gpt-4o configured, embeddings disabled. Configuration status alone does not prove an AI network request succeeds.
- Fresh live Azure probe passed: gpt-4o returned schema-valid SAME_PRODUCT with the supplied candidate and both authorized evidence IDs despite an instruction-bearing source snippet. This single probe verifies connectivity and that case only; it does not certify general prompt-injection resistance.
- Database inspection found four persisted compare_candidates events with actual model response IDs and token usage. These are real provider calls, not simulated stage progress. The recorded tasks are semantic matching; this inspection did not establish a live extraction-fallback or vision request.
- Previous executed checks, retained in implementation-status.md: 35 backend tests, frontend build, real browser workflow, real Docling native/OCR extraction and synthetic benchmarks. Backend unit/integration tests use isolated SQLite, explicitly configured PyMuPDF and disabled AI; they do not establish live AI or Docling accuracy.
- Fifteen executed synthetic scenarios produced expected policy outcomes and zero false approvals. A corrected-truth follow-up of semantic alias, scan and happy path produced line F1=1 and candidate Recall@5=1. The scan follow-up reused cached extraction. An earlier fresh rasterized PO/invoice pair required about 91 seconds.
- Actual 100-PO/60-invoice and multipage examples ran successfully. The 5000/3000 gate and broad cross-domain/corrupted-document coverage were not executed. These are small synthetic tests, not a general accuracy guarantee.

## Requirement comparison

| Area | Current implementation | Assessment |
| --- | --- | --- |
| Provider and structured output | Official SDK, Responses parse, Pydantic schemas, refusal/incomplete guard; ai.py and schemas.py | Integrated; schema validity does not establish factual truth |
| Prompt | Shared untrusted-document instruction plus task-specific extraction/matching instructions | Real prompt; no separate four-role prompts or versioned prompt evaluation |
| Extraction | Docling tables/OCR, PyMuPDF source coordinates, native normalization; AI fallback if no canonical rows | Partial complex-PDF coverage |
| Recovery | ai.py accepts image inputs, but no workflow caller supplies targeted PDF crops | Vision capability is not integrated recovery |
| Matching | Exact SKU/description, lexical/fuzzy/RRF candidates, bounded structured semantic comparison | Real selective AI; most easy cases use rules |
| Evidence safeguards | Candidate/element IDs checked; printed numeric-token checks on AI rows | Partial grounding; no proof that each cited field/value belongs to the correct cell |
| Agent tools | Typed scoped dispatcher for five tools; UI invokes audited evidence lookup | Not wired to model function calling |
| Graph | Durable SQLite checkpoints, linear extract/index/match/validate/report stages, review interrupt | Stateful orchestration; no four-role conditional investigation/recovery loop |
| Human review | Audited corrections, new result version and new graph thread | Working recomputation; not Command(resume=...) of original interrupt |
| Retrieval expansion | Deterministic vocabulary aliases; optional embeddings disabled | Generative dual augmentation and dense retrieval not live verified |
| Global mapping | Transactional ordinary allocation ledger | No OR-Tools split/bundle/global competition solver |
| Specifications | Typed normalization and deterministic supported constraints | Domain-limited; no general specification reasoning agent or full standard/conditional equivalence |
| Local infrastructure | SQLite/WAL, local worker and checkpoints | Authorized substitution for PostgreSQL/Redis/Docker; local single-user scope |

## Accuracy risks found in code

1. Extraction fallback considers only the first 400 elements and runs only when canonical extraction finds zero rows. Partial tables, lost later-page rows or unfamiliar header/column layouts do not trigger adaptive AI recovery. There is no general completeness proof.
2. AI extraction checks referenced numeric tokens, but token presence alone cannot prove column association. Header and attribute grounding are less strict than quantity/price/amount checks. A schema-valid answer can still be factually incorrect.
3. Matching checks that evidence IDs exist in the supplied candidate group, not that every cited ID belongs to the selected candidate or logically proves correspondence. A nonempty evidence list is not sufficient evidence verification.
4. A retrieval score threshold may produce NO_MATCH before semantic verification. Unfamiliar synonyms outside the small vocabulary can be missed; dense/generative recall improvements remain absent.
5. max_agent_tool_calls currently caps semantic model calls per matching pass. It is not a shared workflow tool budget, and there is no actual model-to-tool investigation loop.
6. The request_human_review tool returns a review request object; it does not itself persist a review escalation. The graph's final outcome handling produces the actual review interrupt.
7. Existing tests and synthetic outcomes do not demonstrate robust extraction fallback, targeted vision, severe scan degradation, broad supplier layouts, prompt-injection resistance or all model/network failure cases. One successful safety probe is not a comprehensive adversarial evaluation.

## Changes needed to complete the requested approach

1. Add extraction completeness/quality gates for every page and table, page-bounded structured extraction, and typed crop/OCR/vision recovery. Preserve original and alternative readings, field evidence, verification status and correction provenance; escalate unresolved ambiguity.
2. Implement bounded model function calling using the real typed dispatcher with role-specific tools/prompts, authorized IDs, per-run call/time/token budgets, logged actual requests/results, refusal handling and deterministic review escalation.
3. Extend LangGraph with conditional extraction recovery, matching, specification and exception branches. Define resume versus new-version semantics explicitly and verify both restart and human-review behavior.
4. Ground semantic decisions in invoice and selected-candidate evidence; enforce schema cross-field invariants and field-level numeric/header/attribute source validation. LLM decisions must not override approval policy.
5. Add provenance-labeled generative aliases and configure/test an actual embedding endpoint if retrieval recall requires it. Add OR-Tools for competing/split/bundle assignments and domain-specific constraints as needed.
6. Run a separate live AI/Docling acceptance suite on diverse unseen layouts, long documents, partial tables, degraded scans and difficult domain specifications. Measure extraction field accuracy separately from correspondence F1, candidate recall and false approvals. Test retry/refusal/truncation, invalid IDs, document instructions, budget exhaustion and review escalation.

No credentials, existing reconciliation records or active runs were changed by this audit. These recommendations are not represented as implemented features.
