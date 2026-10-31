#!/bin/sh
# Runs one SINTRA script headless. Output (PNG) is written to /out.
# Override the script with SINTRA_SCRIPT=<file.py> or by passing a script name as the first arg.
set -e
SCRIPT="${1:-${SINTRA_SCRIPT:-sintra_live_mission_demo.py}}"
[ $# -gt 0 ] && shift
cd /out
if [ ! -w /out ]; then
    echo "/out is not writable by uid $(id -u). On NTFS/fuseblk, run as the directory owner: --user \"\$(stat -c '%u:%g' out)\"" >&2
    exit 13
fi
exec python "/app/${SCRIPT}" "$@"
