#!/usr/bin/env python
# pyright: reportMissingImports=false
"""Render a paleotopography PNG from the Scotese PaleoDEM NetCDF files.

Usage: render_topo.py <age_ma> [out_png]
Picks the .nc file in data/paleodem/ whose name starts with the zero-padded age.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from netCDF4 import Dataset

DEM_DIR = Path("data/paleodem")
CPT_PATH = DEM_DIR / "color table for GPlates" / "darkgreen_v23244.cpt"


def load_cpt(path: Path) -> tuple[LinearSegmentedColormap, Normalize]:
    """Parse a GMT CPT file with `v0 r0 g0 b0  v1 r1 g1 b1` rows."""
    stops: list[tuple[float, tuple[float, float, float]]] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "B", "F", "N")):
            continue
        parts = s.split()
        if len(parts) < 8:
            continue
        v0, r0, g0, b0, v1, r1, g1, b1 = (float(x) for x in parts[:8])
        stops.append((v0, (r0 / 255, g0 / 255, b0 / 255)))
        stops.append((v1, (r1 / 255, g1 / 255, b1 / 255)))
    if not stops:
        raise ValueError(f"no color stops parsed from {path}")
    vmin = stops[0][0]
    vmax = stops[-1][0]
    cmap = LinearSegmentedColormap.from_list(
        path.stem,
        [((v - vmin) / (vmax - vmin), rgb) for v, rgb in stops],
        N=1024,
    )
    return cmap, Normalize(vmin=vmin, vmax=vmax, clip=True)


def find_nc(age_ma: int) -> Path:
    prefix = f"{age_ma:03d}_"
    matches = sorted(DEM_DIR.glob(f"{prefix}*.nc"))
    if not matches:
        raise FileNotFoundError(f"no NetCDF in {DEM_DIR} starting with '{prefix}'")
    return matches[0]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: render_topo.py <age_ma> [out_png]", file=sys.stderr)
        return 2
    age = int(sys.argv[1])
    out_png = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"/tmp/paleotopo_{age:03d}ma.png")

    nc_path = find_nc(age)
    print(f"loading {nc_path}", file=sys.stderr)
    with Dataset(nc_path) as ds:
        # Try common variable names; fall back to first 2D variable.
        var_name = next(
            (v for v in ("z", "elevation", "topo", "Band1") if v in ds.variables),
            next((v for v, var in ds.variables.items() if var.ndim == 2), None),
        )
        if var_name is None:
            raise SystemExit(f"could not find a 2D variable in {nc_path}; vars: {list(ds.variables)}")
        elev = np.asarray(ds.variables[var_name][:])

    # Equirectangular: assume rows are lat (top→bottom = +90→-90) and cols are lon.
    print(f"shape={elev.shape} min={np.nanmin(elev):.0f} max={np.nanmax(elev):.0f}", file=sys.stderr)

    cmap, norm = load_cpt(CPT_PATH)
    fig = plt.figure(figsize=(elev.shape[1] / 100, elev.shape[0] / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.imshow(elev, cmap=cmap, norm=norm, interpolation="nearest")
    fig.savefig(out_png, dpi=100, pad_inches=0)
    print(out_png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
