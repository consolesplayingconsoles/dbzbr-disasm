#!/usr/bin/env bash
# Prepare the disassembly from YOUR OWN ROM: check it is the supported release, then generate the
# source (build/src/: one file per routine, the data between them) and check it rebuilds the ROM
# byte for byte. Nothing from the game is stored in git.
#   bash setup.sh <path to your ROM, or a .zip holding it>
set -euo pipefail
cd "$(dirname "$0")"
ROM="${1:?usage: bash setup.sh <your ROM or .zip>}"
SHA1="5ff71986f4911b5dfd16598a5a3a9ba398c92c60"                                    # of the supported release
mkdir -p build
case "$ROM" in
  *.zip|*.ZIP) python3 - "$ROM" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
big = max(z.infolist(), key=lambda i: i.file_size)
open('build/rom.bin', 'wb').write(z.read(big))
PY
  ;;
  *) cp "$ROM" build/rom.bin ;;
esac
got="$( (sha1sum build/rom.bin 2>/dev/null || shasum -a 1 build/rom.bin) | cut -d' ' -f1)"
[ "$got" = "$SHA1" ] || { echo "[ERROR] the ROM has SHA-1 $got, expected $SHA1: not the supported release (see README)"; exit 1; }
chmod +x build.sh setup.sh 2>/dev/null || true
if grep -q '^AS_PATH=' .env 2>/dev/null; then
  bash build.sh
else
  echo "Ready. Tell it where AS (asl and p2bin) is, then build:"
  echo "  echo 'AS_PATH=\"/path/to/the folder with asl and p2bin\"' > \"$PWD/.env\""
  echo "  bash \"$PWD/build.sh\""
fi
