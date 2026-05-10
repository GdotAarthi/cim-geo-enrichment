"""
CIM ↔ GIS Fuzzy Substation Matcher
Matches substation names across CIM and GIS using rapidfuzz,
with voltage level as a mandatory pre-filter.
"""

import re
import logging
from dataclasses import dataclass, asdict

import pandas as pd
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

AUTO_ACCEPT_THRESHOLD = 90
REVIEW_THRESHOLD      = 60
KV_TOLERANCE          = 1.0

ABBREVIATION_MAP = {
    r"\bjunction\b":     "jct",
    r"\bsubstation\b":   "",
    r"\bstation\b":      "",
    r"\b(sub)\b":        "",
    r"\b(ss)\b":         "",
    r"\btransmission\b": "",
    r"\bpower\b":        "",
    r"\bnorth\b":        "n",
    r"\bsouth\b":        "s",
    r"\beast\b":         "e",
    r"\bwest\b":         "w",
    r"\bnorthern\b":     "n",
    r"\bsouthern\b":     "s",
    r"\beastern\b":      "e",
    r"\bwestern\b":      "w",
}


@dataclass
class MatchResult:
    sub_id:          str
    sub_name:        str
    sub_name_clean:  str
    voltage_kv:      float | None
    gis_id:          str | None
    station_name:    str | None
    latitude:        float | None
    longitude:       float | None
    match_score:     float | None
    match_status:    str    # "auto" | "review" | "no_match"
    candidates_seen: int
    notes:           str = ""


def clean_name(raw: str) -> str:
    """Normalise a substation name for fuzzy comparison."""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.lower().strip()
    for sep in [" - ", " – ", ": ", " | "]:
        if sep in s:
            s = s.split(sep, 1)[-1].strip()
    s = re.sub(r"\d+\.?\d*\s*kv\b", "", s)
    for pattern, repl in ABBREVIATION_MAP.items():
        s = re.sub(pattern, repl, s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def voltages_match(a: float, b: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= KV_TOLERANCE
    except (TypeError, ValueError):
        return False


def match_one(cim_row: pd.Series, gis_df: pd.DataFrame) -> MatchResult:
    sub_id    = cim_row["sub_id"]
    sub_name  = cim_row["sub_name"]
    sub_clean = cim_row["sub_name_clean"]
    voltage   = cim_row["voltage_kv"]

    candidates = gis_df[
        gis_df["voltage_kv"].apply(lambda g: voltages_match(voltage, g))
    ].copy() if pd.notna(voltage) else gis_df.copy()

    if candidates.empty:
        return MatchResult(
            sub_id=sub_id, sub_name=sub_name, sub_name_clean=sub_clean,
            voltage_kv=voltage, gis_id=None, station_name=None,
            latitude=None, longitude=None, match_score=None,
            match_status="no_match", candidates_seen=0,
            notes=f"No GIS candidates at {voltage}kV"
        )

    choices  = candidates["station_name_clean"].tolist()
    result   = process.extractOne(sub_clean, choices, scorer=fuzz.token_sort_ratio)
    best_match, best_score, best_idx = result
    best_row = candidates.iloc[best_idx]

    status = (
        "auto"     if best_score >= AUTO_ACCEPT_THRESHOLD else
        "review"   if best_score >= REVIEW_THRESHOLD      else
        "no_match"
    )

    return MatchResult(
        sub_id=sub_id, sub_name=sub_name, sub_name_clean=sub_clean,
        voltage_kv=voltage,
        gis_id=best_row["gis_id"],
        station_name=best_row["station_name"],
        latitude=best_row["latitude"]  if status != "no_match" else None,
        longitude=best_row["longitude"] if status != "no_match" else None,
        match_score=round(best_score, 2),
        match_status=status,
        candidates_seen=len(candidates),
        notes="" if status != "no_match" else f"Best score {best_score:.1f} below threshold"
    )


def run_matching(cim_df: pd.DataFrame, gis_df: pd.DataFrame) -> pd.DataFrame:
    """
    Run full matching pipeline. Returns DataFrame with one row per CIM substation.
    Only processes rows where has_location is False.
    """
    cim_df = cim_df.copy()
    gis_df = gis_df.copy()
    cim_df["sub_name_clean"]      = cim_df["sub_name"].apply(clean_name)
    gis_df["station_name_clean"]  = gis_df["station_name"].apply(clean_name)

    needs_match = cim_df[~cim_df["has_location"]]
    results = [match_one(row, gis_df) for _, row in needs_match.iterrows()]
    return pd.DataFrame([asdict(r) for r in results])


def split_results(df: pd.DataFrame):
    """Split into (auto, review, no_match) DataFrames."""
    return (
        df[df["match_status"] == "auto"].copy(),
        df[df["match_status"] == "review"].copy(),
        df[df["match_status"] == "no_match"].copy(),
    )
