#!/usr/bin/env python
"""Quick smoke test for worker.py. Sends a ping and a small reconstruct request,
prints both responses. Useful for verifying framing before wiring up Elixir."""
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("GPLATES_PYTHON", "python")
MODEL = os.environ.get("GPLATES_MODEL_DIR", str(ROOT / "models" / "paleomap"))


def send(p, msg):
    payload = json.dumps(msg).encode("utf-8")
    p.stdin.write(struct.pack(">I", len(payload)) + payload)
    p.stdin.flush()


def recv(p):
    hdr = p.stdout.read(4)
    if len(hdr) < 4:
        raise RuntimeError("worker closed stdout")
    (n,) = struct.unpack(">I", hdr)
    return json.loads(p.stdout.read(n))


def main():
    print(f"spawning worker (python={PYTHON} model={MODEL})", file=sys.stderr)
    p = subprocess.Popen(
        [PYTHON, str(ROOT / "scripts" / "worker.py"), MODEL],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
    )
    try:
        t0 = time.time()
        send(p, {"id": 1, "op": "ping"})
        print("ping:", recv(p), f"({(time.time() - t0) * 1000:.0f} ms incl. cold start)")

        t0 = time.time()
        send(p, {"id": 2, "op": "reconstruct",
                 "params": {"age": 100, "points": [[48.85, 2.35], [-33.87, 151.21], [40.71, -74.01]]}})
        print("reconstruct 3pts @ 100 Ma:", recv(p), f"({(time.time() - t0) * 1000:.0f} ms)")

        t0 = time.time()
        points = [[lat, lon] for lat in range(-80, 81, 10) for lon in range(-180, 181, 10)]
        send(p, {"id": 3, "op": "reconstruct", "params": {"age": 200, "points": points}})
        r = recv(p)
        n = len(r["result"]["results"])
        print(f"reconstruct {n} pts @ 200 Ma: {(time.time() - t0) * 1000:.0f} ms")
    finally:
        p.stdin.close()
        p.wait(timeout=5)


if __name__ == "__main__":
    main()
