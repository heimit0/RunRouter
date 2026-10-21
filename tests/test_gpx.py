"""GPX serialization tests."""

import xml.etree.ElementTree as ET

from runrouter import gpx

_NS = "http://www.topografix.com/GPX/1/1"


def test_gpx_is_valid_track():
    xml = gpx.to_gpx(
        "Testroute",
        [(52.52, 13.405), (52.53, 13.406), (52.54, 13.407)],
        distance_m=3000,
        duration_s=1500,
    )
    root = ET.fromstring(xml)
    assert root.tag == f"{{{_NS}}}gpx"
    assert root.get("version") == "1.1"

    points = root.findall(f".//{{{_NS}}}trkpt")
    assert len(points) == 3
    assert points[0].get("lat") == "52.5200000"
    assert points[0].get("lon") == "13.4050000"

    name = root.find(f".//{{{_NS}}}trk/{{{_NS}}}name")
    assert name is not None and name.text == "Testroute"


def test_gpx_empty_coords():
    xml = gpx.to_gpx("Leer", [], distance_m=0, duration_s=0)
    root = ET.fromstring(xml)
    assert root.findall(f".//{{{_NS}}}trkpt") == []
