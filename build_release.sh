#!/usr/bin/env bash
# Build a flat AnkiWeb .ankiaddon archive from the Focus Friends source folder.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-}"
if [[ -z "$VERSION" || "$VERSION" == */* || "$VERSION" == *..* ]]; then
  echo "Usage: $0 VERSION (for example: 1.0.0)" >&2
  exit 2
fi

OUT_DIR="$ROOT/dist"
OUT="$OUT_DIR/Focus_Friends-${VERSION}.ankiaddon"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$OUT_DIR"

for file in __init__.py manifest.json config.json README.md config.md kawaii-messages.md; do
  cp "$ROOT/$file" "$STAGE/$file"
done
cp -R "$ROOT/img" "$STAGE/img"
if [[ -f "$ROOT/LICENSE" ]]; then
  cp "$ROOT/LICENSE" "$STAGE/LICENSE"
else
  echo "Note: no LICENSE file found; add the chosen code license before public distribution." >&2
fi

rm -f "$OUT"
(
  cd "$STAGE"
  zip -X -qr "$OUT" .
)
echo "Created $OUT"
