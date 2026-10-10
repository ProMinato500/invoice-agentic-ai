# Bounded workflow and tools

LangGraph persists stage progress and an explicit human-review interrupt in SQLite. Recalculation creates a new result version/thread, retaining prior checkpoints and review provenance. AI is not asked to calculate money or allocate stock.

The current typed allowlist exposes get_po_line, get_invoice_line, get_source_evidence, get_previous_allocations and request_human_review. Dispatch validates schema, run ownership, selected PO scope and source record IDs. Arbitrary SQL/shell/file access is not available. Actual dispatch results write workflow events.

Candidate verification and difficult-layout normalization use Structured Outputs with an instruction that document content is untrusted data. Returned IDs must belong to the bounded authorized context. API errors/refusals cause explicit failure or review, not fabricated output.

The original brief's full four-role autonomous exception/vision tool graph, learned reranker and all typed recovery tools are not claimed as complete. The local UI investigation button performs an actual audited evidence lookup, labeled accordingly.
