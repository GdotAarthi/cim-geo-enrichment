# CIM Geo-Enrichment Tool

> **Fuzzy-match substation names between an IEC 61970 CIM model and a GIS dataset,
> then write geo-coordinates back into the CIM/XML as standard Location objects.**

![CI](https://github.com/YOUR_USERNAME/cim-geo-enrichment/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.37-red)

---

## The problem

CIM/XML network models (IEC 61968/61970) often lack geo-coordinates for substations. GIS systems hold accurate location data but use different, inconsistently formatted station names. A direct join fails because:

- CIM: `"Ridgeline - Maplewood North Substation"`
- GIS: `"MAPLEWOOD NORTH 500KV SUB"`

This tool bridges that gap with a three-stage pipeline:

```
CIM/XML  ──► extract substations ──┐
                                    ├──► fuzzy match + voltage filter ──► enrich CIM/XML
GIS CSV  ──► load stations     ──┘
```

---

## Features

- **Name normalisation** — strips utility prefixes, kV suffixes, expands abbreviations (Junction → JCT) identically on both sides before scoring
- **Voltage pre-filter** — restricts GIS candidates to the same kV level before fuzzy scoring, preventing cross-voltage false matches
- **Confidence split** — auto-accept (≥90), manual review (60–89), no-match (<60) with configurable thresholds
- **Interactive map** — Folium map showing all matched substations colour-coded by confidence
- **CIM write-back** — injects standard `cim:Location` + `cim:PositionPoint` triples, preserving the original RDF graph
- **Audit log** — every match decision exported to CSV for traceability
- **Validation** — post-write checks on coordinate ranges and Location object counts

---

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/cim-geo-enrichment
cd cim-geo-enrichment
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run src/ui/app.py
```

The app opens at `http://localhost:8501`. Use the built-in sample files to see a full demo immediately.

---

## Your own data

**CIM file** — any IEC 61970 CGMES RDF/XML file. Substations without a `cim:Location` triple will be matched.

**GIS CSV** — must have these columns:

| Column | Type | Example |
|---|---|---|
| `gis_id` | str | `GIS_101` |
| `station_name` | str | `MAPLEWOOD NORTH SUB` |
| `voltage_kv` | float | `345` |
| `latitude` | float | `37.8124` |
| `longitude` | float | `-82.3401` |

---

## Project structure

```
cim-geo-enrichment/
├── data/
│   ├── raw/
│   │   ├── sample_cim.xml       # Synthetic IEC 61970 CIM model
│   │   └── sample_gis.csv       # Synthetic GIS station data
│   └── processed/               # Output files (gitignored)
├── src/
│   ├── parser/
│   │   └── cim_extractor.py     # rdflib-based CIM substation extractor
│   ├── matcher/
│   │   └── fuzzy_matcher.py     # rapidfuzz + voltage filter matching engine
│   ├── writer/
│   │   └── cim_writer.py        # Location triple injection + validation
│   └── ui/
│       └── app.py               # Streamlit 6-step UI
├── tests/
│   └── test_pipeline.py
├── docs/adr/
│   └── ADR-001-fuzzy-scorer.md
└── .github/workflows/ci.yml
```

---

## How the matching works

1. **`clean_name()`** normalises both CIM and GIS names identically:
   - Lowercase, strip utility prefix (before ` - `)
   - Remove embedded kV values (`138KV` → `""`)
   - Expand abbreviations (`junction` → `jct`, `substation` → `""`)
   - Remove punctuation and extra whitespace

2. **Voltage pre-filter** restricts GIS candidates to `|cim_kv - gis_kv| ≤ 1.0`

3. **`rapidfuzz.token_sort_ratio`** scores the cleaned names — sorts tokens alphabetically before comparing, handling word-order variation

4. Results split by score: ≥90 auto, 60–89 review, <60 no-match

See [ADR-001](docs/adr/ADR-001-fuzzy-scorer.md) for scorer selection rationale.

---

## Data notice

> All CIM and GIS data in this repository is **synthetic**, generated for demonstration
> purposes. The utility "Ridgeline Power Grid" and region "Appalachian Highlands" are
> fictional. Substation names, IDs, impedance values, and coordinates do not represent
> any real network.

---

## Author

**Aarthi Gajendran** · [LinkedIn](https://linkedin.com/in/aarthi-gajendran)

*Built to demonstrate CIM data engineering + fuzzy record linkage for AI Architect and Data Platform roles in the energy sector.*
