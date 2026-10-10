# Research and official references

The implementation uses structured source data and feedback provenance, conservative product/specification separation, candidate retrieval/fusion, bounded structured semantic comparison and deterministic financial rules. It does not claim a learned ranker, BM25 in PostgreSQL, or research-paper accuracy.

- [Online Similarity Learning with Feedback for Invoice Line Item Matching](https://arxiv.org/abs/2001.00288): reviewer labels/candidate features motivate future ranker training. No LightGBM model is deployed.
- [Dual-Augmentation RAG research reference supplied in the brief](https://doi.org/10.3390/jrfm19060402): searchable aliases remain non-authoritative. The current local implementation uses deterministic vocabulary expansion; generative dual augmentation is not certified.
- [Docling pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/) and [document converter](https://docling-project.github.io/docling/reference/document_converter/): retain structured layout/table/OCR output. The installed version uses `format_options`.
- [Official OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs): Pydantic response schemas through `responses.parse`, refusal/error handling and bounded candidate IDs.
- [Official OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings): configurable model/dimensions; no Azure embedding deployment is assumed from the chat deployment.

Documentation pages were consulted during implementation; the configured Azure deployment was verified with a live Structured Outputs response. This does not certify every optional model/API capability.
