#!/usr/bin/env python
# pyright: reportAttributeAccessIssue=false
"""Reconstruct a present-day (lat, lon) to its paleo position at a given age.

Usage: reconstruct.py <lat> <lon> <age_ma> [model_dir]
Outputs JSON to stdout.
"""
import json
import sys
from pathlib import Path

import pygplates


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: reconstruct.py <lat> <lon> <age_ma> [model_dir]", file=sys.stderr)
        return 2

    lat = float(sys.argv[1])
    lon = float(sys.argv[2])
    age = float(sys.argv[3])
    model_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("models/muller2022")

    rot_files = list((model_dir / "Rotations").glob("*.rot"))
    static_files = list((model_dir / "StaticPolygons").glob("*.gpml*")) + \
                   list((model_dir / "StaticPolygons").glob("*.shp"))

    rotation_model = pygplates.RotationModel([str(f) for f in rot_files])
    static_polygons = [pygplates.FeatureCollection(str(f)) for f in static_files]

    point = pygplates.PointOnSphere(lat, lon)

    # Wrap the point in a feature so we can use PlatePartitioner.
    point_feature = pygplates.Feature()
    point_feature.set_geometry(point)

    partitioner = pygplates.PlatePartitioner(static_polygons, rotation_model)
    partitioned = partitioner.partition_features([point_feature])

    if not partitioned:
        print(json.dumps({"error": "point did not intersect any static polygon"}))
        return 1

    plate_id = partitioned[0].get_reconstruction_plate_id()
    rotation = rotation_model.get_rotation(age, plate_id)
    paleo = rotation * point
    paleo_lat, paleo_lon = paleo.to_lat_lon()

    print(json.dumps({
        "present": [lat, lon],
        "age": age,
        "paleo": [paleo_lat, paleo_lon],
        "plate_id": plate_id,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
