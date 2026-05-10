# ADR-001: Fuzzy matching scorer — token_sort_ratio vs token_set_ratio

**Date:** 2025-05-10  
**Status:** Accepted

## Context

Substation names between CIM and GIS sources differ in multiple ways:
- Word order: "Charlotte North Sub" vs "North Charlotte Substation"
- Abbreviations: "Junction" vs "JCT"
- Prefixes/suffixes: utility name prefix in CIM, kV suffix in GIS

Two rapidfuzz scorers were evaluated:

| Scorer | How it works | Strength |
|---|---|---|
| `token_sort_ratio` | Sorts tokens alphabetically then scores | Handles word-order variation |
| `token_set_ratio` | Scores intersection + remainder | Handles containment (one name is a subset of the other) |

## Decision

Use `token_sort_ratio` as the primary scorer, applied **after** `clean_name` normalisation.

Rationale: The `clean_name` function removes prefixes, suffixes, and abbreviations before scoring. After cleaning, names are short (2–3 tokens) and the main variation is word order — exactly what `token_sort_ratio` handles best. `token_set_ratio` would score false positives when a short GIS name partially matches a longer CIM name.

## Consequences

- Matching quality is highly sensitive to `clean_name` correctness. If a utility uses unusual abbreviations, `ABBREVIATION_MAP` must be extended.
- A second pass with `token_set_ratio` could be added for the `no_match` tier as a fallback scorer, at the cost of more false positives entering the review bucket.
