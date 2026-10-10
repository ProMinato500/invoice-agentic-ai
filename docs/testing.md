# Testing

Run `python -m pytest -q` through the workspace virtual environment. Offline integration tests upload generated real PDFs, use the explicit PyMuPDF parser, run the real persisted workflow, check specification/financial outcomes, verify evidence, create reports, audit review and corrections, reject malicious tools and verify evaluation isolation. Test configuration points to new temporary directories, not workspace data. No inference test receives ground truth.

The live application uses Docling standard layout/table/OCR. Its synthetic benchmark runs the same ingestion/workflow and loads truth only afterwards. Live Azure semantic calls are tracked in workflow event usage payloads. Failure and review are measured outcomes, not replaced with fabricated success.

`frontend/tests/local-flow.spec.ts` exercises real uploads, SSE replay, original PDF.js source rendering, source captions, documented review, recomputation, report downloads, refresh/history and all navigation screens. It records screenshots and failure traces. First cold model initialization and ongoing benchmarks can lengthen the test; limits permit those real operations.

Do not treat a successful build or a small synthetic benchmark as proof of all edge cases. The 5000/3000 CLI can generate a stress input, but its full performance gate has not yet been certified.
