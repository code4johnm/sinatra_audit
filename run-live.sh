#!/bin/sh
# Local run of the locked-down live interceptor.
# Prefer uid 10001. On filesystems that ignore chmod (NTFS/fuseblk), the bind
# mount stays owned by the host user, so fall back to that owner. Otherwise
# savefig dies with PermissionError after a full cycle.
set -eu
cd "$(dirname "$0")"
mkdir -p output
chmod 1777 output 2>/dev/null || true

if ! docker image inspect sinatra-sandbox:local >/dev/null 2>&1; then
    docker build -t sinatra-sandbox:local .
fi

run_user="10001:10001"
if ! docker run --rm --user 10001:10001 --network none --entrypoint python \
    -v "$PWD/output:/output" -w /output \
    sinatra-sandbox:local -c 'import os,sys; sys.exit(0 if os.access(".", os.W_OK | os.X_OK) else 1)'
then
    run_user="$(stat -c '%u:%g' output)"
    echo "uid 10001 cannot write output/. Using directory owner ${run_user}." >&2
fi

exec docker run --rm --name sinatra-live \
    --user "$run_user" --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    --pids-limit 128 --memory 4g --memory-swap 4g --cpus 2 \
    --tmpfs /tmp:rw,nosuid,nodev,mode=1777,size=512m \
    -v "$PWD/output:/output" \
    -e MPLBACKEND=Agg -e MPLCONFIGDIR=/tmp/mpl -e HOME=/tmp \
    -w /output sinatra-sandbox:local
