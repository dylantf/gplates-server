#!/usr/bin/env python
# pyright: reportAttributeAccessIssue=false
"""Batch reconstruct present-day (lat, lon) points to paleo positions at a given age.

Reads JSON from stdin:
  {"age": <ma>, "points": [[lat, lon], ...], "model_dir": "<optional path>"}

Writes JSON to stdout:
  {"age": <ma>, "results": [
      {"present": [lat, lon], "paleo": [lat, lon], "plate_id": <int>},
      {"present": [lat, lon], "paleo": null, "plate_id": null},  # for unpartitioned points
      ...
  ]}

CLI fallback (single point):
  reconstruct.py <lat> <lon> <age_ma> [model_dir]
"""
import json
import sys
from pathlib import Path

import pygplates


def reconstruct_batch(age: float, points: list[list[float]], model_dir: Path) -> list[dict]:
    rot_files = list((model_dir / "Rotations").glob("*.rot"))
    static_files = list((model_dir / "StaticPolygons").glob("*.gpml*")) + \
                   list((model_dir / "StaticPolygons").glob("*.shp"))

    rotation_model = pygplates.RotationModel([str(f) for f in rot_files])
    static_polygons = [pygplates.FeatureCollection(str(f)) for f in static_files]

    # Tag each input feature with its index so we can look up the result.
    point_features = []
    for i, (lat, lon) in enumerate(points):
        f = pygplates.Feature()
        f.set_geometry(pygplates.PointOnSphere(lat, lon))
        f.set_name(str(i))
        point_features.append(f)

    partitioner = pygplates.PlatePartitioner(static_polygons, rotation_model)
    partitioned = partitioner.partition_features(point_features)

    # Cache one rotation per plate_id (could be hundreds of points per plate).
    rotation_cache: dict[int, object] = {}
    results: list[dict | None] = [None] * len(points)

    for f in partitioned:
        try:
            idx = int(f.get_name())
        except (ValueError, TypeError):
            continue
        plate_id = f.get_reconstruction_plate_id()
        if plate_id not in rotation_cache:
            rotation_cache[plate_id] = rotation_model.get_rotation(age, plate_id)
        rotation = rotation_cache[plate_id]
        lat, lon = points[idx]
        paleo_pt = rotation * pygplates.PointOnSphere(lat, lon)
        paleo_lat, paleo_lon = paleo_pt.to_lat_lon()
        results[idx] = {
            "present": [lat, lon],
            "paleo": [paleo_lat, paleo_lon],
            "plate_id": plate_id,
        }

    for i, r in enumerate(results):
        if r is None:
            results[i] = {"present": points[i], "paleo": None, "plate_id": None}

    return results  # type: ignore[return-value]


def main() -> int:
    # CLI fallback: <lat> <lon> <age_ma> [model_dir]
    if len(sys.argv) >= 4 and sys.argv[1].lstrip("-").replace(".", "", 1).isdigit():
        lat = float(sys.argv[1])
        lon = float(sys.argv[2])
        age = float(sys.argv[3])
        model_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("models/paleomap")
        results = reconstruct_batch(age, [[lat, lon]], model_dir)
        json.dump({"age": age, "results": results}, sys.stdout)
        return 0

    # Batch mode via stdin JSON.
    data = json.load(sys.stdin)
    age = float(data["age"])
    points = data["points"]
    model_dir = Path(data.get("model_dir") or (sys.argv[1] if len(sys.argv) > 1 else "models/paleomap"))

    results = reconstruct_batch(age, points, model_dir)
    json.dump({"age": age, "results": results}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
