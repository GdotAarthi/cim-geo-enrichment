"""
CIM Substation Extractor
Parses IEC 61970 CIM/XML and extracts Substation objects with their
primary voltage levels, ready for GIS matching.
"""

from rdflib import Graph, Namespace, RDF
from dataclasses import dataclass
from typing import Optional
import logging
import pandas as pd

logger = logging.getLogger(__name__)
CIM = Namespace("http://iec.ch/TC57/2013/CIM-schema-cim16#")


@dataclass
class SubstationRecord:
    sub_id:      str
    sub_name:    str
    description: str
    voltage_kv:  Optional[float]
    region:      Optional[str]
    has_location: bool = False


def _short(uri: str) -> str:
    return uri.split("#")[-1] if "#" in uri else uri.split("/")[-1]


def _val(graph: Graph, subj, prop: str) -> Optional[str]:
    v = graph.value(subj, CIM[prop])
    return str(v) if v else None


def extract_substations(xml_path: str) -> pd.DataFrame:
    """
    Parse a CIM/XML file and return a DataFrame of substations.

    Returns columns:
        sub_id, sub_name, description, voltage_kv, region, has_location
    """
    g = Graph()
    g.parse(xml_path, format="xml")
    logger.info(f"Loaded {len(g)} triples from {xml_path}")

    # Build voltage level map: substation_id → set of kV values
    vl_map: dict[str, list[float]] = {}
    for vl in g.subjects(RDF.type, CIM["VoltageLevel"]):
        sub_ref = g.value(vl, CIM["VoltageLevel.Substation"])
        bv_ref  = g.value(vl, CIM["VoltageLevel.BaseVoltage"])
        if sub_ref and bv_ref:
            sub_id = _short(str(sub_ref))
            nom_v  = g.value(bv_ref, CIM["BaseVoltage.nominalVoltage"])
            if nom_v:
                vl_map.setdefault(sub_id, []).append(float(str(nom_v)))

    # Build location map: substation_id → bool (has Location)
    loc_ids: set[str] = set()
    for loc in g.subjects(RDF.type, CIM["Location"]):
        for subj, pred, obj in g.triples((None, CIM["PowerSystemResource.Location"], loc)):
            loc_ids.add(_short(str(subj)))

    records = []
    for sub in g.subjects(RDF.type, CIM["Substation"]):
        sub_id  = _short(str(sub))
        name    = _val(g, sub, "IdentifiedObject.name") or sub_id
        desc    = _val(g, sub, "IdentifiedObject.description") or ""
        region_ref = g.value(sub, CIM["Substation.Region"])
        region  = None
        if region_ref:
            region = _val(g, region_ref, "IdentifiedObject.name")

        kv_list = vl_map.get(sub_id, [])
        # Use the highest voltage level as the primary matching voltage
        voltage_kv = max(kv_list) if kv_list else None

        records.append(SubstationRecord(
            sub_id=sub_id,
            sub_name=name,
            description=desc,
            voltage_kv=voltage_kv,
            region=region,
            has_location=(sub_id in loc_ids),
        ))

    df = pd.DataFrame([r.__dict__ for r in records])
    logger.info(f"Extracted {len(df)} substations — "
                f"{df['has_location'].sum()} already have coordinates")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = extract_substations("../../data/raw/sample_cim.xml")
    print(df.to_string(index=False))
