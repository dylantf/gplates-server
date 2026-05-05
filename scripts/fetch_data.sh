#!/usr/bin/env bash
# Fetch the PaleoMAP PaleoDEM rasters and plate model from Zenodo.
# https://zenodo.org/records/10659112  (CC BY 4.0)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/data" 2>/dev/null || { mkdir -p "$ROOT/data"; cd "$ROOT/data"; }

PALEODEM_URL='https://zenodo.org/api/records/10659112/files/5a.%20PaleoDEM%20(nc,%203601x1801).zip/content'
PLATEMODEL_URL='https://zenodo.org/api/records/10659112/files/3a.%20PALEOMAP%20Global%20Plate%20Model%20for%20Paleogeographic%20Reconstructions%20v.19o_r1d.zip/content'

if [ ! -d paleodem ]; then
  echo "downloading paleodem (~129 MB)..."
  curl -L -o paleodem.zip "$PALEODEM_URL"
  unzip -q paleodem.zip -d paleodem/
  rm paleodem.zip
else
  echo "paleodem/ already present, skipping"
fi

if [ ! -d plate-model ]; then
  echo "downloading plate model (~19 MB)..."
  curl -L -o plate-model.zip "$PLATEMODEL_URL"
  unzip -q plate-model.zip -d plate-model/
  rm plate-model.zip
else
  echo "plate-model/ already present, skipping"
fi

echo "done. relinking models/paleomap symlinks..."
mkdir -p "$ROOT/models/paleomap"/{Rotations,StaticPolygons,Coastlines}
ln -sf ../../../data/plate-model/Scotese_Plate_Model_forPgeog_v19o_r1d_v240506a.rot \
  "$ROOT/models/paleomap/Rotations/"
ln -sf ../../../data/plate-model/Scotese_Plate_Polygons__forPgeog_v19o_v240506.gpml \
  "$ROOT/models/paleomap/StaticPolygons/"
ln -sf ../../../data/plate-model/Scotese_Just_Coastlines_19o.gpmlz \
  "$ROOT/models/paleomap/Coastlines/"

echo "all good."
