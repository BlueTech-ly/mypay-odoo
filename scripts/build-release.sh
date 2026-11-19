#!/usr/bin/env bash
# Build clean Odoo Apps upload zips for payment_mypay and pos_mypay.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
VERSION="$(grep -E "^\s*'version':" "$ROOT/payment_mypay/__manifest__.py" | head -1 | sed -E "s/.*'version':[[:space:]]*'([^']+)'.*/\1/")"

rm -rf "$DIST"
mkdir -p "$DIST"

# Remove local junk that must never ship.
find "$ROOT/payment_mypay" "$ROOT/pos_mypay" \
  \( -name '__pycache__' -o -name '*.py[cod]' -o -name '.DS_Store' \) \
  -print0 | xargs -0 rm -rf

package_module() {
  local name="$1"
  local zipname="${name}-${VERSION}.zip"
  (
    cd "$ROOT"
    zip -r "$DIST/$zipname" "$name" \
      -x "*/__pycache__/*" \
      -x "*.pyc" \
      -x "*.pyo" \
      -x "*/.DS_Store" \
      -x "*/*.DS_Store"
  )
  echo "Created $DIST/$zipname"
}

package_module payment_mypay
package_module pos_mypay

# Combined bundle for private deploy (addons path drop-in).
(
  cd "$ROOT"
  zip -r "$DIST/mypay-odoo-${VERSION}.zip" payment_mypay pos_mypay README.md LICENSE \
    -x "*/__pycache__/*" \
    -x "*.pyc" \
    -x "*.pyo" \
    -x "*/.DS_Store" \
    -x "*/*.DS_Store"
)
echo "Created $DIST/mypay-odoo-${VERSION}.zip"

echo
ls -lh "$DIST"
echo
echo "Upload to Odoo Apps: payment_mypay-${VERSION}.zip and/or pos_mypay-${VERSION}.zip"
echo "Private deploy: mypay-odoo-${VERSION}.zip"
