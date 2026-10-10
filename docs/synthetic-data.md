# Synthetic document factory

`python -m synthetic_data generate --all --seed 42` generates 15 scenario folders plus 12 layout-variant folders. Each includes real purchase_order.pdf/invoice.pdf, manifest, ground truth, expected discrepancies and generation metadata. Default all-generation keeps the large example at 100 PO / 60 invoice lines; explicit `--po-lines` / `--invoice-lines` support requested stress sizes.

Scenarios include exact match, specification/price/quantity/total/currency conflicts, partial billing, extra item, missing specification, conflicting model, semantic alias, identifier ambiguity, full scans, continued tables and a larger document. Layouts vary borders, fonts, orientation, compactness, header metadata columns, service labels, column ordering and rasterization. The catalog currently focuses on fictional laptop configurations. Not all requested industries or corruption variants are covered.

All identities/tax IDs/payment cues are fictional. Seeded generation and invariant PDF output make the same inputs reproducible. The UI loader reads only PDF bytes and public manifest metadata; the evaluator reads isolated truth after inference. True line numbers are normal document row references, not hidden answer labels.

Some alias/ambiguous scenarios intentionally require abstention. Evaluation reports actual outcomes and errors; it does not insert expected decisions into the matching pipeline.
