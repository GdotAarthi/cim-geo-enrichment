"""
CIM Geo-Enrichment Tool — Streamlit UI
Upload a CIM/XML and GIS CSV, run fuzzy matching,
review results, and download the enriched CIM file.
"""

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from io import StringIO, BytesIO
import tempfile
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from parser.cim_extractor  import extract_substations
from matcher.fuzzy_matcher import run_matching, split_results, clean_name
from writer.cim_writer     import inject_coordinates, validate_output

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="CIM Geo-Enrichment",
    page_icon="🗺️",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .metric-card {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 10px;
    padding: 16px 20px;
    text-align: center;
  }
  .metric-card .value { font-size: 2rem; font-weight: 600; }
  .metric-card .label { font-size: 0.8rem; color: #6c757d; text-transform: uppercase; letter-spacing: 0.05em; }
  .status-auto   { color: #198754; font-weight: 600; }
  .status-review { color: #fd7e14; font-weight: 600; }
  .status-none   { color: #dc3545; font-weight: 600; }
  .step-badge {
    display: inline-block;
    background: #0d6efd;
    color: white;
    border-radius: 50%;
    width: 28px; height: 28px;
    text-align: center; line-height: 28px;
    font-weight: 600; font-size: 14px;
    margin-right: 8px;
  }
</style>
""", unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────
st.title("🗺️ CIM Geo-Enrichment Tool")
st.caption(
    "Match substation names between a CIM/XML model and a GIS dataset "
    "using fuzzy matching + voltage filtering, then write coordinates back into the CIM file."
)
st.divider()


# ── Session state ─────────────────────────────────────────────────────────
for key in ["cim_df", "gis_df", "results_df", "cim_xml_path", "enriched_path"]:
    if key not in st.session_state:
        st.session_state[key] = None


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — Upload data
# ═══════════════════════════════════════════════════════════════════════════
st.markdown('<span class="step-badge">1</span> **Upload your data files**', unsafe_allow_html=True)

col_cim, col_gis = st.columns(2)

with col_cim:
    st.markdown("##### CIM/XML model")
    use_sample_cim = st.checkbox("Use sample CIM file", value=True, key="sample_cim")
    if use_sample_cim:
        sample_cim = os.path.join(os.path.dirname(__file__), "../../data/raw/sample_cim.xml")
        st.session_state["cim_xml_path"] = sample_cim
        cim_df = extract_substations(sample_cim)
        st.session_state["cim_df"] = cim_df
        st.success(f"Loaded sample CIM — {len(cim_df)} substations")
    else:
        cim_file = st.file_uploader("Upload CIM/XML (IEC 61970 CGMES)", type=["xml"])
        if cim_file:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
                tmp.write(cim_file.read())
                tmp_path = tmp.name
            st.session_state["cim_xml_path"] = tmp_path
            cim_df = extract_substations(tmp_path)
            st.session_state["cim_df"] = cim_df
            st.success(f"Loaded — {len(cim_df)} substations found")

with col_gis:
    st.markdown("##### GIS dataset")
    use_sample_gis = st.checkbox("Use sample GIS file", value=True, key="sample_gis")
    if use_sample_gis:
        sample_gis = os.path.join(os.path.dirname(__file__), "../../data/raw/sample_gis.csv")
        gis_df = pd.read_csv(sample_gis)
        st.session_state["gis_df"] = gis_df
        st.success(f"Loaded sample GIS — {len(gis_df)} stations")
    else:
        gis_file = st.file_uploader(
            "Upload GIS CSV (columns: gis_id, station_name, voltage_kv, latitude, longitude)",
            type=["csv"]
        )
        if gis_file:
            gis_df = pd.read_csv(gis_file)
            required = {"gis_id", "station_name", "voltage_kv", "latitude", "longitude"}
            missing  = required - set(gis_df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                st.session_state["gis_df"] = gis_df
                st.success(f"Loaded — {len(gis_df)} GIS records")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — Preview inputs
# ═══════════════════════════════════════════════════════════════════════════
if st.session_state["cim_df"] is not None and st.session_state["gis_df"] is not None:

    st.markdown('<span class="step-badge">2</span> **Preview loaded data**', unsafe_allow_html=True)

    tab_cim, tab_gis = st.tabs(["CIM substations", "GIS stations"])

    with tab_cim:
        cim_preview = st.session_state["cim_df"].copy()
        cim_preview["cleaned name"] = cim_preview["sub_name"].apply(clean_name)
        st.dataframe(
            cim_preview[["sub_id", "sub_name", "cleaned name", "voltage_kv", "has_location"]],
            use_container_width=True,
            hide_index=True,
        )
        needs = (~cim_preview["has_location"]).sum()
        st.caption(f"{needs} substation(s) need geo-coordinates")

    with tab_gis:
        gis_preview = st.session_state["gis_df"].copy()
        gis_preview["cleaned name"] = gis_preview["station_name"].apply(clean_name)
        st.dataframe(
            gis_preview[["gis_id", "station_name", "cleaned name", "voltage_kv", "latitude", "longitude"]],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — Configure & run matching
# ═══════════════════════════════════════════════════════════════════════════
if st.session_state["cim_df"] is not None and st.session_state["gis_df"] is not None:

    st.markdown('<span class="step-badge">3</span> **Configure & run matching**', unsafe_allow_html=True)

    with st.expander("⚙️ Matching parameters", expanded=False):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            auto_thresh = st.slider(
                "Auto-accept threshold", 70, 99, 90,
                help="Score ≥ this → coordinates written automatically"
            )
        with col_b:
            review_thresh = st.slider(
                "Review threshold", 40, 89, 60,
                help="Score between review and auto → flagged for manual review"
            )
        with col_c:
            kv_tol = st.slider(
                "Voltage tolerance (kV)", 0.0, 10.0, 1.0, step=0.5,
                help="Allow this much difference between CIM and GIS voltage levels"
            )

    if st.button("▶ Run matching", type="primary", use_container_width=True):
        with st.spinner("Matching substations…"):
            import matcher.fuzzy_matcher as fm
            fm.AUTO_ACCEPT_THRESHOLD = auto_thresh
            fm.REVIEW_THRESHOLD      = review_thresh
            fm.KV_TOLERANCE          = kv_tol

            results = run_matching(
                st.session_state["cim_df"],
                st.session_state["gis_df"],
            )
            st.session_state["results_df"] = results
        st.success("Matching complete!")

    st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — Results
# ═══════════════════════════════════════════════════════════════════════════
if st.session_state["results_df"] is not None:
    results = st.session_state["results_df"]
    auto_df, review_df, none_df = split_results(results)

    st.markdown('<span class="step-badge">4</span> **Match results**', unsafe_allow_html=True)

    # ── Summary metrics ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total substations",   len(results))
    c2.metric("✅ Auto-accepted",     len(auto_df),   delta=f"{len(auto_df)/len(results)*100:.0f}%")
    c3.metric("⚠️ Needs review",      len(review_df), delta=f"{len(review_df)/len(results)*100:.0f}%" if len(review_df) else None)
    c4.metric("❌ No match",          len(none_df),   delta=f"-{len(none_df)/len(results)*100:.0f}%" if len(none_df) else None, delta_color="inverse")

    st.markdown("---")

    # ── Detailed results tabs ──
    tab_all, tab_auto, tab_review, tab_none = st.tabs([
        f"All ({len(results)})",
        f"✅ Auto-accepted ({len(auto_df)})",
        f"⚠️ Review needed ({len(review_df)})",
        f"❌ No match ({len(none_df)})",
    ])

    display_cols = ["sub_id", "sub_name", "voltage_kv", "station_name",
                    "match_score", "match_status", "latitude", "longitude", "candidates_seen"]

    def score_color(val):
        if pd.isna(val): return "color: #dc3545"
        if val >= 90:    return "color: #198754; font-weight:600"
        if val >= 60:    return "color: #fd7e14; font-weight:600"
        return "color: #dc3545"

    def status_color(val):
        if val == "auto":     return "color: #198754; font-weight:600"
        if val == "review":   return "color: #fd7e14; font-weight:600"
        return "color: #dc3545"

    with tab_all:
        styled = (
            results[display_cols]
            .style
            .applymap(score_color,  subset=["match_score"])
            .applymap(status_color, subset=["match_status"])
            .format({"match_score": "{:.1f}", "latitude": "{:.4f}", "longitude": "{:.4f}"}, na_rep="—")
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

    with tab_auto:
        if auto_df.empty:
            st.info("No auto-accepted matches yet. Try lowering the threshold.")
        else:
            st.dataframe(
                auto_df[display_cols].style
                .format({"match_score": "{:.1f}", "latitude": "{:.4f}", "longitude": "{:.4f}"}),
                use_container_width=True, hide_index=True
            )

    with tab_review:
        if review_df.empty:
            st.info("No records need manual review.")
        else:
            st.warning(
                f"{len(review_df)} match(es) scored between {60} and {90}. "
                "Review the names carefully before approving."
            )
            for _, row in review_df.iterrows():
                with st.expander(
                    f"🔍 {row['sub_id']} — score: {row['match_score']:.1f}",
                    expanded=True
                ):
                    rc1, rc2 = st.columns(2)
                    with rc1:
                        st.markdown("**CIM name:**")
                        st.code(row["sub_name"])
                        st.caption(f"Cleaned: `{row['sub_name_clean']}`")
                        st.caption(f"Voltage: {row['voltage_kv']}kV")
                    with rc2:
                        st.markdown("**Best GIS match:**")
                        st.code(row["station_name"])
                        st.caption(f"GIS ID: {row['gis_id']}")
                        st.caption(f"Coords: {row['latitude']:.4f}, {row['longitude']:.4f}")

    with tab_none:
        if none_df.empty:
            st.success("All substations found a match!")
        else:
            st.error(f"{len(none_df)} substation(s) could not be matched.")
            st.dataframe(
                none_df[["sub_id", "sub_name", "voltage_kv", "candidates_seen", "notes"]],
                use_container_width=True, hide_index=True
            )
            st.info("Tips: Check if the GIS file covers this voltage level, "
                    "or lower the review threshold to capture more candidates.")

    st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5 — Map visualisation
# ═══════════════════════════════════════════════════════════════════════════
if st.session_state["results_df"] is not None:
    results = st.session_state["results_df"]
    mapped  = results[results["latitude"].notna()].copy()

    st.markdown('<span class="step-badge">5</span> **Map — matched substation locations**', unsafe_allow_html=True)

    if mapped.empty:
        st.info("No matched coordinates to display yet.")
    else:
        center_lat = mapped["latitude"].mean()
        center_lon = mapped["longitude"].mean()
        m = folium.Map(location=[center_lat, center_lon], zoom_start=9, tiles="CartoDB positron")

        color_map = {"auto": "green", "review": "orange", "no_match": "red"}

        for _, row in mapped.iterrows():
            color = color_map.get(row["match_status"], "gray")
            popup_html = f"""
                <b>{row['sub_id']}</b><br>
                {row['sub_name']}<br>
                <hr style='margin:4px 0'>
                GIS match: <b>{row['station_name']}</b><br>
                Score: <b>{row['match_score']:.1f}</b><br>
                Voltage: {row['voltage_kv']}kV<br>
                Coords: {row['latitude']:.4f}, {row['longitude']:.4f}
            """
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=10,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"{row['sub_id']} — {row['match_score']:.1f}",
            ).add_to(m)

        folium.LayerControl().add_to(m)

        col_map, col_legend = st.columns([4, 1])
        with col_map:
            st_folium(m, width=None, height=480, returned_objects=[])
        with col_legend:
            st.markdown("**Legend**")
            st.markdown("🟢 Auto-accepted")
            st.markdown("🟠 Needs review")
            st.markdown("🔴 No match")
            st.markdown("---")
            st.metric("Mapped", len(mapped))
            st.metric("Unmapped", len(results) - len(mapped))

    st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6 — Write back & download
# ═══════════════════════════════════════════════════════════════════════════
if st.session_state["results_df"] is not None:
    results = st.session_state["results_df"]
    auto_df, review_df, _ = split_results(results)

    st.markdown('<span class="step-badge">6</span> **Write coordinates back to CIM & download**', unsafe_allow_html=True)

    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        include_review = st.checkbox(
            "Include manually reviewed matches",
            value=False,
            help="Also inject review-tier matches. Only check if you have inspected them above."
        )
    with col_opt2:
        create_backup = st.checkbox("Create .bak backup of original CIM file", value=True)

    to_inject = pd.concat([auto_df, review_df]) if include_review else auto_df

    st.info(
        f"Ready to inject **{len(to_inject)}** coordinate set(s) into the CIM file. "
        f"({'Auto + review' if include_review else 'Auto-accepted only'})"
    )

    if st.button("💾 Generate enriched CIM file", type="primary"):
        if st.session_state["cim_xml_path"] is None:
            st.error("No CIM file loaded.")
        elif to_inject.empty:
            st.warning("No accepted matches to write.")
        else:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp_out:
                output_path = tmp_out.name

            with st.spinner("Writing coordinates into CIM/XML…"):
                write_result = inject_coordinates(
                    source_xml=st.session_state["cim_xml_path"],
                    output_xml=output_path,
                    accepted_df=to_inject,
                    backup=create_backup,
                )
                validation = validate_output(output_path, write_result["injected"])

            # Validation report
            if validation["pass"]:
                st.success(
                    f"✅ Enriched CIM written — "
                    f"{write_result['injected']} Location objects injected, "
                    f"{len(write_result['skipped'])} skipped."
                )
            else:
                st.warning("CIM written but validation flagged issues:")
                st.json(validation)

            # Download button
            with open(output_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download enriched CIM/XML",
                    data=f.read(),
                    file_name="enriched_cim.xml",
                    mime="application/xml",
                    use_container_width=True,
                )

            st.session_state["enriched_path"] = output_path

    st.divider()

    # ── Audit log download ──
    st.markdown("##### 📋 Audit log")
    st.caption(
        "Download the complete match log for traceability — "
        "every coordinate decision is recorded."
    )
    audit_csv = results.to_csv(index=False)
    st.download_button(
        label="⬇️ Download audit log (CSV)",
        data=audit_csv,
        file_name="match_audit.csv",
        mime="text/csv",
        use_container_width=False,
    )
