#!/usr/bin/env sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: ./scripts/release.sh VERSION [MESSAGE] [--no-push] [--publish]" >&2
  exit 2
fi

VERSION=$1
shift
MESSAGE="release $VERSION"
if [ "$#" -gt 0 ] && [ "${1#--}" = "$1" ]; then
  MESSAGE=$1
  shift
fi

NO_PUSH=0
PUBLISH=0
for option in "$@"; do
  case "$option" in
    --no-push) NO_PUSH=1 ;;
    --publish) PUBLISH=1 ;;
    *) echo "Unknown option: $option" >&2; exit 2 ;;
  esac
done

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PYTHON=${PYTHON:-python3}

"$PYTHON" scripts/release_preflight.py --structure-only
git add -A
if ! git diff --cached --quiet; then
  git commit -m "$MESSAGE"
fi

if [ "$NO_PUSH" -eq 0 ]; then
  git push origin "$(git branch --show-current)"
fi

TARGET=$("$PYTHON" scripts/source_release.py host-target)
OUTPUT="$ROOT/.release-assets"
WORK="$ROOT/.source-work/$TARGET"
rm -rf "$OUTPUT"
"$PYTHON" scripts/source_release.py build \
  --target "$TARGET" --version "$VERSION" \
  --output-dir "$OUTPUT" --work-dir "$WORK"

if [ "$PUBLISH" -eq 1 ]; then
  command -v gh >/dev/null 2>&1 || { echo "GitHub CLI is required" >&2; exit 1; }
  if gh release view "$VERSION" >/dev/null 2>&1; then
    gh release upload "$VERSION" "$OUTPUT"/* --clobber
  else
    gh release create "$VERSION" "$OUTPUT"/* --title "$VERSION" --notes "$MESSAGE"
  fi
fi

printf 'Built source package:\n'
find "$OUTPUT" -type f -print
