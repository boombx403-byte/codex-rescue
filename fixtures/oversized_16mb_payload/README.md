# oversized_16mb_payload

Synthetic privacy-safe fixture verifying JSONL records exceeding 16 MiB (>16,777,216 bytes).

Expected primary class: `OVERSIZED_PAYLOAD` with finding `VALID_BUT_OVERSIZED`.
`verify` is expected to return `REVIEW_REQUIRED`.
Recovery plan generation is expected to refuse applicable repair / mutation to prevent data loss.
