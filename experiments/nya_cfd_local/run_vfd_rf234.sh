#!/usr/bin/env bash
set -eo pipefail

pilot_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case_name="${1:-qa_vfd_rf2_3_4_80_dt05}"
if [[ ! "$case_name" =~ ^qa_[A-Za-z0-9_-]+$ ]]; then
    printf 'Invalid case name: %s\n' "$case_name" >&2
    exit 2
fi
case="$pilot_dir/$case_name"
test -f "$case/metadata.json"
test ! -e "$case/foamRun.log"
run_dir="$(mktemp -d "/var/tmp/nya-${case_name}-XXXXXXXX")"
printf '%s\n' "$run_dir" > "$case/linux_run_dir.txt"
cp -a "$case/0" "$case/constant" "$case/system" "$run_dir/"
source /opt/openfoam14/etc/bashrc
set -u
cd "$run_dir"
checkMesh -allTopology -allGeometry > checkMesh.log 2>&1
cp checkMesh.log "$case/checkMesh.log"
grep -q 'Mesh OK\.' checkMesh.log
foamRun > foamRun.log 2>&1
cp foamRun.log "$case/foamRun.log"
grep -q '^End$' foamRun.log
foamToVTK -ascii -fields '(U)' > foamToVTK.log 2>&1
cp foamToVTK.log "$case/foamToVTK.log"
cp -a VTK "$case/"
printf 'Completed %s in %s\n' "$(basename "$case")" "$run_dir"
