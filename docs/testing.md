# Testing

Run `python -m pytest -q` through the workspace virtual environment. Offline integration tests upload generated real PDFs, use the explicit PyMuPDF parser, run the real persisted workflow, check specification/financial outcomes, verify evidence, create reports, audit review and corrections, reject malicious tools and verify evaluation isolation. Test configuration points to new temporary directories, not workspace data. No inference test receives ground truth.

The live application uses Docling standard layout/table/OCR. Its synthetic benchmark runs the same ingestion/workflow and loads truth only afterwards. Live Azure semantic calls are tracked in workflow event usage payloads. Failure and review are measured outcomes, not replaced with fabricated success.

`frontend/tests/local-flow.spec.ts` exercises real uploads, SSE replay, original PDF.js source rendering, source captions, documented review, recomputation, report downloads, refresh/history and all navigation screens. It records screenshots and failure traces. First cold model initialization and ongoing benchmarks can lengthen the test; limits permit those real operations.

Do not treat a successful build or a small synthetic benchmark as proof of all edge cases. The 5000/3000 CLI can generate a stress input, but its full performance gate has not yet been certified.

## Follow-up verification

Backend: 50 tests passed. Production build and TypeScript passed. Both Playwright workflows passed (1.7m): real uploads, active SSE streaming chunks, updated results/findings, reviewer substitution/recompute, source pixels, reports, reload and clickable OCR/output traces.

Run .venv/Scripts/python.exe -m scripts.live_agentic_check for the credential-dependent live suite. It uses actual worker/Docling/Azure calls on isolated synthetic runs and preserves successful output under storage/live-agentic-acceptance.json. The executed suite verified four tool-using roles, unfamiliar-layout recovery and source vision output. Unit tests separately mock provider responses; they never count as live model accuracy measurements.

The failed noncanonical-field live attempt and browser stale-update attempt led to real fixes and repeated verification; neither is hidden or reported as an initial success. The new local encoder was downloaded and tested with actual normalized vectors. The earlier fifteen-scenario benchmark is historical and was not silently attributed to the updated implementation.
