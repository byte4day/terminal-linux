#!/usr/bin/env bash
# Download a trimmed Openbox binary + Clearlooks theme into src/terminal_linux/vendor/openbox (Arch package).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/src/terminal_linux/vendor/openbox"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="${OPENBOX_PKG_URL:-https://archlinux.org/packages/extra/x86_64/openbox/download/}"
echo "Fetching $URL"
curl -fsSL "$URL" -o "$TMP/openbox.pkg.tar.zst"
mkdir -p "$TMP/extract"
tar -I zstd -xf "$TMP/openbox.pkg.tar.zst" -C "$TMP/extract"

rm -rf "$DEST"
mkdir -p "$DEST/usr/bin" "$DEST/usr/lib" "$DEST/usr/share/themes" "$DEST/etc"
cp -a "$TMP/extract/usr/bin/openbox" "$DEST/usr/bin/"
cp -a "$TMP/extract/usr/lib"/libob*.so* "$DEST/usr/lib/"
cp -a "$TMP/extract/usr/share/themes/Clearlooks" "$DEST/usr/share/themes/" 2>/dev/null || true
cp -a "$TMP/extract/etc/xdg" "$DEST/etc/" 2>/dev/null || true
cat >"$DEST/NOTICE" <<'EOF'
Openbox (https://openbox.org/) — GNU GPL version 2.
Fetched for hosts without a system openbox package.
EOF
echo "Installed vendored openbox → $DEST"
