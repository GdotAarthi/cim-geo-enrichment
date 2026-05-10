"""
CIM Location Writer
Injects geo-coordinates into a CIM/XML file as IEC 61970 Location
and PositionPoint objects linked to each Substation.
"""

from rdflib import Graph, Namespace, RDF, Literal, URIRef
from rdflib.namespace import XSD
import pandas as pd
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
CIM  = Namespace("http://iec.ch/TC57/2013/CIM-schema-cim16#")
BASE = "urn:uuid:"


def _sub_uri(graph: Graph, sub_id: str) -> URIRef | None:
    """Find the URIRef for a Substation by its local ID fragment."""
    for s in graph.subjects(RDF.type, CIM["Substation"]):
        if str(s).endswith(sub_id) or str(s).endswith(f"#{sub_id}"):
            return s
    return None


def inject_coordinates(
    source_xml:   str,
    output_xml:   str,
    accepted_df:  pd.DataFrame,
    backup:       bool = True,
) -> dict:
    """
    Inject lat/lon into a CIM/XML file for all rows in accepted_df.

    Each substation gets:
        cim:Location  (new object, linked via PowerSystemResource.Location)
        cim:PositionPoint (linked to the Location, carries lat/lon)

    Args:
        source_xml:  Path to the input CIM/XML file
        output_xml:  Path to write the enriched CIM/XML file
        accepted_df: DataFrame with columns sub_id, latitude, longitude, gis_id
        backup:      If True, copies the source file to source_xml.bak first

    Returns:
        dict with keys: injected, skipped, output_path
    """
    if backup:
        shutil.copy2(source_xml, source_xml + ".bak")
        logger.info(f"Backup written → {source_xml}.bak")

    g = Graph()
    g.parse(source_xml, format="xml")
    g.bind("cim", CIM)

    injected = 0
    skipped  = []

    for _, row in accepted_df.iterrows():
        sub_id = row["sub_id"]
        lat    = row["latitude"]
        lon    = row["longitude"]
        gis_id = row.get("gis_id", "unknown")

        sub_uri = _sub_uri(g, sub_id)
        if sub_uri is None:
            logger.warning(f"  Substation {sub_id} not found in CIM graph — skipped")
            skipped.append(sub_id)
            continue

        # Already has a location? Skip to avoid overwrite
        if g.value(sub_uri, CIM["PowerSystemResource.Location"]):
            logger.info(f"  {sub_id} already has a Location — skipped")
            skipped.append(sub_id)
            continue

        loc_id  = URIRef(f"{BASE}LOC_{sub_id}")
        pp_id   = URIRef(f"{BASE}PP_{sub_id}_1")

        g.add((loc_id, RDF.type,              CIM["Location"]))
        g.add((loc_id, CIM["IdentifiedObject.name"],
               Literal(f"Location_{sub_id}", datatype=XSD.string)))
        g.add((loc_id, CIM["Location.CoordinateSystem"],
               Literal("WGS84", datatype=XSD.string)))
        g.add((loc_id, CIM["Location.gisSource"],
               Literal(str(gis_id), datatype=XSD.string)))

        g.add((pp_id, RDF.type,                   CIM["PositionPoint"]))
        g.add((pp_id, CIM["PositionPoint.Location"], loc_id))
        g.add((pp_id, CIM["PositionPoint.sequenceNumber"],
               Literal("1", datatype=XSD.integer)))
        g.add((pp_id, CIM["PositionPoint.xPosition"],
               Literal(str(lon), datatype=XSD.float)))
        g.add((pp_id, CIM["PositionPoint.yPosition"],
               Literal(str(lat), datatype=XSD.float)))

        g.add((sub_uri, CIM["PowerSystemResource.Location"], loc_id))

        logger.info(f"  Injected ({lat}, {lon}) → {sub_id}")
        injected += 1

    Path(output_xml).parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=output_xml, format="xml")
    logger.info(f"Enriched CIM written → {output_xml} "
                f"({injected} injected, {len(skipped)} skipped)")

    return {"injected": injected, "skipped": skipped, "output_path": output_xml}


def validate_output(output_xml: str, expected_count: int) -> dict:
    """
    Quick sanity check on the enriched CIM file.
    Returns dict with pass/fail flags.
    """
    g = Graph()
    g.parse(output_xml, format="xml")

    loc_count = sum(1 for _ in g.subjects(RDF.type, CIM["Location"]))
    pp_count  = sum(1 for _ in g.subjects(RDF.type, CIM["PositionPoint"]))

    # Coord range check (valid WGS84)
    bad_coords = []
    for pp in g.subjects(RDF.type, CIM["PositionPoint"]):
        lat = g.value(pp, CIM["PositionPoint.yPosition"])
        lon = g.value(pp, CIM["PositionPoint.xPosition"])
        if lat and lon:
            if not (-90 <= float(str(lat)) <= 90):
                bad_coords.append(f"lat {lat} out of range")
            if not (-180 <= float(str(lon)) <= 180):
                bad_coords.append(f"lon {lon} out of range")

    return {
        "location_count":  loc_count,
        "position_points": pp_count,
        "expected":        expected_count,
        "count_ok":        loc_count == expected_count,
        "coords_ok":       len(bad_coords) == 0,
        "bad_coords":      bad_coords,
        "pass":            loc_count == expected_count and len(bad_coords) == 0,
    }
