# Matching and validation

SKU normalization removes spacing/punctuation but keeps distinct alphanumeric versions. A unique exact SKU establishes product correspondence; conflicting technical configuration is independently reported. Identical descriptions without contradictory identifiers can establish correspondence. Multiple PO lines sharing an identifier are not automatically collapsed.

SQLite FTS5 retrieves lexical candidates; RapidFuzz ranks original descriptions. Reciprocal-rank fusion uses k=60. Deterministic dual-sided vocabulary normalization is labeled as a retrieval aid. No learned ranking model is claimed. Optional dense retrieval uses exact cosine similarity of stored OpenAI vectors, not a second database.

Only bounded candidate groups are sent to Structured Outputs. The response must reference actual candidate IDs and supplied source IDs. DIFFERENT and NO_MATCH clear mappings. UNKNOWN/UNCERTAIN/SAME_FAMILY require review. The maximum semantic-call count is per matching stage; no autonomous unlimited agent loop exists.

Typed attributes currently cover common IT specifications, power, voltage, IP rating, dimensions, material grade, warranty and model identifiers. Pint handles supported conversions. Missing required attributes return UNKNOWN, conflicts return FAIL, and unsupported operators return UNKNOWN. Certification, conditional constraints and packaging equivalence are not inferred from similarity.

Decimal checks compare unit price, quantities, remaining cumulative quantity, line extended amounts, subtotal, grand total, currency, supplier/buyer identity, PO reference and duplicate invoice identity. Missing total/tax bases are review findings. Price tolerance does not authorize a different product. Normal partial invoices do not report every unbilled PO line as a discrepancy.

AUTO_APPROVABLE means the implemented checks passed; it does not trigger payment or certify unsupported contract conditions.
