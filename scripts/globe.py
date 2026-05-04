#!/usr/bin/env python
"""Build a GeoJSON FeatureCollection of the globe at a given age.

Bundles three layers:
  - coastlines (lines)
  - continental polygons (polygons)
  - resolved plate boundaries (lines, with boundary_type)

Usage: globe.py <age_ma> [model_dir]
Outputs GeoJSON to stdout.
"""
import json
import sys
from pathlib import Path

import antimeridian
import pygplates
import shapely
import shapely.geometry
import shapely.ops


def _load_collections(dir_path: Path) -> list:
    if not dir_path.exists():
        return []
    files = list(dir_path.glob("*.gpml*")) + list(dir_path.glob("*.shp"))
    return [pygplates.FeatureCollection(str(f)) for f in files]


def _polyline_coords(geom) -> list:
    return [[lon, lat] for lat, lon in geom.to_lat_lon_list()]


def _polygon_coords(geom) -> list:
    # GeoJSON polygons are arrays of linear rings; first = exterior.
    # fix_shape (called later) handles dedup, winding, and antimeridian splitting.
    ring = [[lon, lat] for lat, lon in geom.to_lat_lon_list()]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return [ring]


def _geom_to_geojson(geom) -> dict | None:
    if isinstance(geom, pygplates.PolygonOnSphere):
        return {"type": "Polygon", "coordinates": _polygon_coords(geom)}
    if isinstance(geom, pygplates.PolylineOnSphere):
        return {"type": "LineString", "coordinates": _polyline_coords(geom)}
    if isinstance(geom, pygplates.PointOnSphere):
        lat, lon = geom.to_lat_lon()
        return {"type": "Point", "coordinates": [lon, lat]}
    return None


SIMPLIFY_TOLERANCE_DEG = 1.0


def _fix_antimeridian(gj: dict) -> dict:
    # fix_shape handles winding, dedup, and antimeridian splitting.
    # Polygons crossing the dateline are upgraded to MultiPolygon.
    if gj["type"] not in ("Polygon", "MultiPolygon", "LineString", "MultiLineString"):
        return gj
    try:
        return antimeridian.fix_shape(gj, fix_winding=True)
    except Exception as e:
        # Degenerate geometry — keep the raw shape and let the renderer cope.
        print(f"antimeridian fix skipped: {e}", file=sys.stderr)
        return gj


def _simplify(gj: dict) -> dict | None:
    if gj["type"] not in ("Polygon", "MultiPolygon", "LineString", "MultiLineString"):
        return gj
    try:
        shp = shapely.geometry.shape(gj).simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
    except Exception as e:
        print(f"simplify skipped: {e}", file=sys.stderr)
        return gj
    if shp.is_empty:
        return None
    return shapely.geometry.mapping(shp)


def _reconstructed_features(feature_collections, rotation_model, age, layer_name):
    """Return raw reconstructed features as GeoJSON dicts. No simplify/antimeridian fix
    here — those are applied post-dissolve so the union sees full-resolution geometry."""
    out = []
    if not feature_collections:
        return out
    reconstructed = []
    pygplates.reconstruct(feature_collections, rotation_model, reconstructed, age)
    for rfg in reconstructed:
        feat = rfg.get_feature()
        gj = _geom_to_geojson(rfg.get_reconstructed_geometry())
        if gj is None:
            continue
        out.append({
            "type": "Feature",
            "geometry": gj,
            "properties": {
                "layer": layer_name,
                "plate_id": feat.get_reconstruction_plate_id(),
                "name": feat.get_name() or None,
            },
        })
    return out


def _boundary_subtype(feature) -> str:
    ft = feature.get_feature_type()
    name = ft.to_qualified_string().split(":")[-1] if ft else "Unknown"
    return name


def _resolved_boundaries(topology_collections, rotation_model, age):
    out = []
    if not topology_collections:
        return out
    resolved_topologies = []
    shared_boundary_sections = []
    pygplates.resolve_topologies(
        topology_collections,
        rotation_model,
        resolved_topologies,
        age,
        shared_boundary_sections,
    )
    for section in shared_boundary_sections:
        feat = section.get_feature()
        for sub in section.get_shared_sub_segments():
            gj = _geom_to_geojson(sub.get_resolved_geometry())
            if gj is None:
                continue
            out.append({
                "type": "Feature",
                "geometry": gj,
                "properties": {
                    "layer": "boundary",
                    "boundary_type": _boundary_subtype(feat),
                    "name": feat.get_name() or None,
                },
            })
    return out


def _polygonal_only(shp):
    """make_valid can return GeometryCollection (Polygon + LineString); keep polygons."""
    if shp.geom_type in ("Polygon", "MultiPolygon"):
        return shp
    if shp.geom_type == "GeometryCollection":
        polys = [g for g in shp.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        return shapely.ops.unary_union(polys)
    return None


def _dissolve(features: list, properties: dict) -> dict | None:
    """Union features → simplify → antimeridian-fix → GeoJSON Feature."""
    if not features:
        return None
    is_polygonal = features[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    shapes = []
    for f in features:
        try:
            shp = shapely.geometry.shape(f["geometry"])
            if not shp.is_valid:
                shp = shapely.make_valid(shp)
                if is_polygonal:
                    shp = _polygonal_only(shp)
            if shp is not None and not shp.is_empty:
                shapes.append(shp)
        except Exception as e:
            print(f"dissolve skipped one shape: {e}", file=sys.stderr)
    if not shapes:
        return None
    try:
        merged = shapely.ops.unary_union(shapes)
    except Exception as e:
        print(f"unary_union failed: {e}", file=sys.stderr)
        return None
    if merged.is_empty:
        return None
    try:
        merged = merged.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
    except Exception as e:
        print(f"post-dissolve simplify skipped: {e}", file=sys.stderr)
    gj = shapely.geometry.mapping(merged)
    gj = _fix_antimeridian(gj)
    return {"type": "Feature", "geometry": gj, "properties": properties}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: globe.py <age_ma> [model_dir]", file=sys.stderr)
        return 2

    age = float(sys.argv[1])
    model_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("models/muller2022")

    rot_files = list((model_dir / "Rotations").glob("*.rot"))
    rotation_model = pygplates.RotationModel([str(f) for f in rot_files])

    coastlines = _load_collections(model_dir / "Coastlines")
    continents = _load_collections(model_dir / "ContinentalPolygons")
    topologies = _load_collections(model_dir / "Topologies")

    raw_continents = _reconstructed_features(continents, rotation_model, age, "continent")
    raw_coastlines = _reconstructed_features(coastlines, rotation_model, age, "coastline")
    raw_boundaries = _resolved_boundaries(topologies, rotation_model, age)

    features: list = []
    cont = _dissolve(raw_continents, {"layer": "continent"})
    if cont:
        features.append(cont)
    coast = _dissolve(raw_coastlines, {"layer": "coastline"})
    if coast:
        features.append(coast)

    by_type: dict[str, list] = {}
    for f in raw_boundaries:
        by_type.setdefault(f["properties"]["boundary_type"], []).append(f)
    for btype, group in by_type.items():
        feat = _dissolve(group, {"layer": "boundary", "boundary_type": btype})
        if feat:
            features.append(feat)

    json.dump({"type": "FeatureCollection", "age": age, "features": features}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
