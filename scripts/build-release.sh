#!/usr/bin/env bash
# S-CLAW for Linux (AppImage) and macOS (dmg).
#
# The same app as on Windows, without a brain inside: on first start it offers to
# download one (Settings > Claw's brain), or to use your own GGUF file. The llama.cpp
# engine is included. OCR uses the system's Tesseract (apt install tesseract-ocr /
# brew install tesseract); without it, scanned pages say so and everything else works.
#
#   scripts/build-release.sh            # on Linux -> build/app-local/*.AppImage
#   scripts/build-release.sh            # on macOS -> build/app-local/*.dmg
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
stage="$root/build/stage-unix"
os="$(uname -s)"
case "$os" in
  Linux)  asset_re='bin-ubuntu-x64\.(zip|tar\.gz)$'; target="AppImage"; flag="--linux" ;;
  Darwin) asset_re='bin-macos-arm64\.(zip|tar\.gz)$'; target="dmg"; flag="--mac" ;;
  *) echo "Unsupported system: $os" >&2; exit 1 ;;
esac
rm -rf "$stage"; mkdir -p "$stage"/{engine,tesseract,models}

echo "== Python environment and frozen backend"
cd "$root/backend"
python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt pyinstaller==6.16.0
.venv/bin/python packaging/build_backend.py --out "$stage/_frozen"
mv "$stage/_frozen/claw-backend" "$stage/backend"; rm -rf "$stage/_frozen"

echo "== llama.cpp engine"
auth=(); [ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")
url=""
for page in 1 2 3; do
  url=$(curl -fsSL "${auth[@]}" "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30&page=$page" \
        | python3 -c "import json,re,sys; rs=json.load(sys.stdin); print(next((a['browser_download_url'] for r in rs for a in r['assets'] if re.search(r'$asset_re', a['name'])), ''))")
  [ -n "$url" ] && break
done
[ -n "$url" ] || { echo "No llama.cpp build for this system in the recent releases." >&2; exit 1; }
echo "   $url"
tmp="$(mktemp -d)"; curl -fsSL "$url" -o "$tmp/engine.pkg"
case "$url" in *.zip) unzip -q "$tmp/engine.pkg" -d "$tmp/x" ;; *) mkdir -p "$tmp/x"; tar -xzf "$tmp/engine.pkg" -C "$tmp/x" ;; esac
srv="$(find "$tmp/x" -name llama-server -type f | head -1)"
[ -n "$srv" ] || { echo "llama-server was not in the download." >&2; exit 1; }
cp -R "$(dirname "$srv")"/. "$stage/engine/"; chmod +x "$stage/engine/llama-server"
basename "$url" > "$stage/engine/VERSION.txt"

printf '{"id": "local", "name": "Claw Local", "local_inference": true, "service_url": "", "service_token": "", "bundled_model": ""}\n' > "$stage/edition.json"

echo "== Electron app ($target)"
cd "$root/desktop"
npm ci --no-audit --no-fund
CLAW_STAGE="$stage" CLAW_EDITION=Local CLAW_UNIX_TARGET="$target" npx electron-builder --config electron-builder.config.js "$flag"
ls -la "$root/build/app-local"
