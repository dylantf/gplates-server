#!/usr/bin/env python
# pyright: reportAttributeAccessIssue=false
"""Long-lived pygplates worker. Reads length-prefixed JSON requests from stdin,
writes length-prefixed JSON responses to stdout. Loads the rotation model and
static polygons once at startup so subsequent reconstructions are fast.

Framing: 4-byte big-endian length prefix, then UTF-8 JSON payload.
Matches Erlang `Port.open(..., {:packet, 4})`.

Request:  {"id": <int>, "op": "<name>", "params": {...}}
Response: {"id": <int>, "result": {...}}    on success
          {"id": <int>, "error": "<msg>"}   on error

Usage: worker.py <model_dir>
"""
import json
import struct
import sys
import traceback
from pathlib import Path

import pygplates


def load_model(model_dir: Path) -> dict:
    rot_files = list((model_dir / "Rotations").glob("*.rot"))
    static_files = list((model_dir / "StaticPolygons").glob("*.gpml*")) + \
                   list((model_dir / "StaticPolygons").glob("*.shp"))
    rotation_model = pygplates.RotationModel([str(f) for f in rot_files])
    static_polygons = [pygplates.FeatureCollection(str(f)) for f in static_files]
    partitioner = pygplates.PlatePartitioner(static_polygons, rotation_model)
    return {"rotation_model": rotation_model, "partitioner": partitioner}


def op_reconstruct(state: dict, *, age: float, points: list[list[float]]) -> dict:
    rotation_model = state["rotation_model"]
    partitioner = state["partitioner"]

    point_features = []
    for i, (lat, lon) in enumerate(points):
        f = pygplates.Feature()
        f.set_geometry(pygplates.PointOnSphere(lat, lon))
        f.set_name(str(i))
        point_features.append(f)

    partitioned = partitioner.partition_features(point_features)
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

    return {"age": age, "results": results}


def op_ping(state: dict) -> dict:
    return {"pong": True}


DISPATCH = {
    "reconstruct": op_reconstruct,
    "ping": op_ping,
}


def read_packet() -> bytes | None:
    header = sys.stdin.buffer.read(4)
    if len(header) < 4:
        return None  # EOF
    (length,) = struct.unpack(">I", header)
    if length == 0:
        return b""
    buf = b""
    while len(buf) < length:
        chunk = sys.stdin.buffer.read(length - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def write_packet(payload: bytes) -> None:
    sys.stdout.buffer.write(struct.pack(">I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: worker.py <model_dir>", file=sys.stderr)
        return 2
    model_dir = Path(sys.argv[1])

    print(f"loading model from {model_dir}", file=sys.stderr)
    state = load_model(model_dir)
    print("ready", file=sys.stderr)

    while True:
        raw = read_packet()
        if raw is None:
            return 0

        req_id = None
        try:
            req = json.loads(raw)
            req_id = req.get("id")
            op = req["op"]
            params = req.get("params", {})
            handler = DISPATCH.get(op)
            if handler is None:
                resp = {"id": req_id, "error": f"unknown op: {op}"}
            else:
                resp = {"id": req_id, "result": handler(state, **params)}
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            resp = {"id": req_id, "error": str(e)}

        write_packet(json.dumps(resp).encode("utf-8"))


if __name__ == "__main__":
    sys.exit(main())
