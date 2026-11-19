#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
prepared="${1:-$here/qa_supplier20_photo_ampliado_vfd70_dt05}"
reference=/var/tmp/nya-stability-qa.CXX3I8
last_reference="$(find "$reference" -maxdepth 1 -mindepth 1 -type d -name '[0-9]*' | sort -V | tail -1)"
test -n "$last_reference"
test -f "$last_reference/U"
test -f "$prepared/metadata.json"

run_dir="$(mktemp -d /var/tmp/nya-supplier-photo70.XXXXXX)"
printf '%s\n' "$run_dir" > "$prepared/linux_run_dir.txt"
cp -a "$prepared/0" "$prepared/constant" "$prepared/system" "$run_dir/"
cp -a "$last_reference" "$run_dir/"
python3 "$here/patch_warm_start_sources.py" \
    "$run_dir/$(basename "$last_reference")/U" "$prepared/0/U"
sed -i 's/startFrom startTime;/startFrom latestTime;/; s/endTime 1200;/endTime 1800;/; s/maxCo 0.2;/maxCo 0.5;/' "$run_dir/system/controlDict"

export HOME=/root USER=root FOAM_INST_DIR=/opt WM_PROJECT_DIR=/opt/openfoam14 WM_PROJECT_VERSION=14
export FOAM_APPBIN=/opt/openfoam14/platforms/linux64GccDPInt32Opt/bin
export LD_LIBRARY_PATH=/opt/openfoam14/platforms/linux64GccDPInt32Opt/lib/openmpi-system:/opt/openfoam14/platforms/linux64GccDPInt32Opt/lib
export PATH="$FOAM_APPBIN:/usr/bin:/bin"

cd "$run_dir"
checkMesh -case "$run_dir" > "$run_dir/checkMesh.log" 2>&1
cp "$run_dir/checkMesh.log" "$prepared/checkMesh.log"
grep -q 'Mesh OK\.' "$run_dir/checkMesh.log"
foamRun -case "$run_dir" > "$run_dir/foamRun.log" 2>&1
cp "$run_dir/foamRun.log" "$prepared/foamRun.log"
grep -q '^End$' "$run_dir/foamRun.log"
foamToVTK -case "$run_dir" -ascii -fields '(U)' > "$run_dir/foamToVTK.log" 2>&1
cp "$run_dir/foamToVTK.log" "$prepared/foamToVTK.log"
mkdir -p "$prepared/VTK"
cp -a "$run_dir/VTK/." "$prepared/VTK/"
printf 'Completed photo layout from %s in %s\n' "$(basename "$last_reference")" "$run_dir"
