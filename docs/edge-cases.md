# Verified and unverified cases

Automated offline assertions cover exact SKU, ambiguous duplicate SKU, specification mismatch/absence/model conflict, price/quantity/total/currency conflicts, valid partial billing, duplicate invoicing, idempotent creation, review/substitution, canonical correction/recomputation, malformed uploads, unauthorized records, tool allowlist and evaluation isolation.

The live benchmark also exercises extra items, semantic alias, scanned OCR, continued tables and a 100/60-line example. See implementation-status.md for measured outcomes.

Unsupported/uncertain contract semantics remain review-required rather than inferred: complex bundles/split mappings, packaging conversion without a verified basis, credit-note linkage, receipts/amendments, FX, inclusive or mixed tax, unknown standard versions and conditional requirements. The complete corruption/security/fault-injection matrix in the brief has not been exhausted.
