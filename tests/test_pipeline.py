"""Unit tests for CIM geo-enrichment pipeline."""
import pytest
import pandas as pd
import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.matcher.fuzzy_matcher import clean_name, voltages_match, run_matching, split_results
from src.parser.cim_extractor  import extract_substations

SAMPLE_CIM = os.path.join(os.path.dirname(__file__), "../data/raw/sample_cim.xml")
SAMPLE_GIS = os.path.join(os.path.dirname(__file__), "../data/raw/sample_gis.csv")


# ── clean_name ──────────────────────────────────────────────────────────
class TestCleanName:
    def test_strips_utility_prefix(self):
        assert "maplewood n" in clean_name("Ridgeline - Maplewood North Substation")

    def test_removes_kv_from_name(self):
        result = clean_name("GASTONIA SS 138KV")
        assert "138" not in result
        assert "kv" not in result

    def test_lowercases(self):
        assert clean_name("CHARLOTTE NORTH") == clean_name("charlotte north")

    def test_abbreviation_junction(self):
        assert clean_name("Cedarville Junction") == clean_name("Cedarville JCT")

    def test_empty_string(self):
        assert clean_name("") == ""

    def test_none_input(self):
        assert clean_name(None) == ""

    def test_strips_substation_suffix(self):
        r = clean_name("Ironbridge Substation")
        assert "substation" not in r


# ── voltages_match ───────────────────────────────────────────────────────
class TestVoltagesMatch:
    def test_exact_match(self):      assert voltages_match(138.0, 138.0)
    def test_within_tolerance(self): assert voltages_match(138.0, 138.5)
    def test_outside_tolerance(self):assert not voltages_match(138.0, 345.0)
    def test_none_value(self):       assert not voltages_match(None, 138.0)
    def test_string_input(self):     assert voltages_match("138", "138.0")


# ── CIM extractor ────────────────────────────────────────────────────────
class TestCIMExtractor:
    def test_returns_dataframe(self):
        df = extract_substations(SAMPLE_CIM)
        assert isinstance(df, pd.DataFrame)

    def test_required_columns(self):
        df = extract_substations(SAMPLE_CIM)
        for col in ["sub_id", "sub_name", "voltage_kv", "has_location"]:
            assert col in df.columns

    def test_finds_substations(self):
        df = extract_substations(SAMPLE_CIM)
        assert len(df) >= 1

    def test_no_real_company_names(self):
        df = extract_substations(SAMPLE_CIM)
        for name in df["sub_name"]:
            assert "duke energy" not in name.lower()
            assert "edf" not in name.lower()


# ── Matching pipeline ────────────────────────────────────────────────────
class TestMatching:
    @pytest.fixture
    def sample_data(self):
        cim_df = extract_substations(SAMPLE_CIM)
        gis_df = pd.read_csv(SAMPLE_GIS)
        return cim_df, gis_df

    def test_run_matching_returns_dataframe(self, sample_data):
        cim_df, gis_df = sample_data
        results = run_matching(cim_df, gis_df)
        assert isinstance(results, pd.DataFrame)

    def test_result_has_required_columns(self, sample_data):
        cim_df, gis_df = sample_data
        results = run_matching(cim_df, gis_df)
        for col in ["sub_id", "match_score", "match_status", "latitude", "longitude"]:
            assert col in results.columns

    def test_split_covers_all_rows(self, sample_data):
        cim_df, gis_df = sample_data
        results = run_matching(cim_df, gis_df)
        auto, review, none_ = split_results(results)
        assert len(auto) + len(review) + len(none_) == len(results)

    def test_skips_already_located(self, sample_data):
        cim_df, gis_df = sample_data
        cim_df = cim_df.copy()
        cim_df["has_location"] = True
        results = run_matching(cim_df, gis_df)
        assert len(results) == 0

    def test_auto_scores_above_threshold(self, sample_data):
        cim_df, gis_df = sample_data
        results = run_matching(cim_df, gis_df)
        auto, _, _ = split_results(results)
        if not auto.empty:
            assert (auto["match_score"] >= 90).all()
