# Bounded agents and inspectable execution

The local runtime uses four real reasoning roles: extraction recovery, matching, specification and exception investigation. The official Responses function-calling loop requires a real tool inspection before a final structured decision. Tools validate typed arguments, selected-run/document/organization scope and source IDs. No arbitrary shell, SQL, remote URL or filesystem tools are exposed.

Every provider request, public structured response, actual tool request/result/error, OCR output, match decision, solver plan and validation result is persisted as a trace. SSE carries compact event references and drains terminal history before sending settled. The UI expands stages and opens saved outputs; original sources remain inspectable beside OCR text. Private model reasoning and credentials are not displayed.

Prompts are versioned reconcile-v2 and isolate source document instructions. The workflow has per-run request/token/tool budgets restored from durable events, a per-role turn limit, provider timeout/retries, job timeout, cancellation guards and conservative failure/review handling. Defaults are 48 model requests, 180000 consumed tokens, 24 tool calls and at most 24 recovery pages; token limits are checked between requests, so one response can take consumption above the limit before subsequent calls stop.

Extraction checks page coverage, unreadable rows, missing headers and subtotal coverage. Suspect pages are processed in bounded chunks with field-cited Structured Outputs and optional actual source-crop vision recovery. Competing readings and proposals are retained. Model readings require source verification; a vision reading alone is not independent numeric evidence.

Matching inspects scoped sources/candidates, can expand terminology through a search tool and requires invoice plus selected-candidate citations for correspondence. Specifications can add missing printed attributes with citations, preserving existing facts; these additions require reviewer verification. Deterministic constraints decide compliance. Exception investigations annotate and persist review requests; they cannot override money, duplicate checks, capacity or approval policy.

LangGraph checkpoints and human interrupts are durable in SQLite. When review creates a new result version, the prior checkpoint is resumed/closed with a version guard, and the corrected inputs are recomputed in a new thread. A superseded checkpoint cannot overwrite the new result.

The OR-Tools planner proposes globally capacity-compatible exact/verified edges, split quantities and unallocated demand. Review can authorize compatible-unit splits with a note; the ledger commits individual edges only after all financial/specification checks pass. Product bundles requiring component conversions or unstated grouping remain unresolved rather than receiving forced allocations.

Dense retrieval uses a downloaded local all-MiniLM-L6-v2 encoder with normalized mean pooling, SQLite-stored vectors and exact cosine ranking; lexical/fuzzy/dense rankings are fused. Generative PO aliases and model-proposed invoice search expansions are non-authoritative retrieval aids. OpenAI/Azure embeddings remain selectable when a genuine embedding deployment is configured.

References used for the integration: [Responses function calling](https://developers.openai.com/api/docs/guides/function-calling), [image inputs](https://developers.openai.com/api/docs/guides/images-vision), [local encoder model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2).
