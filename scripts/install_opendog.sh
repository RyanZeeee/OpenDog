#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
USER_BASE="$("$PYTHON_BIN" -m site --user-base)"
USER_BIN="$USER_BASE/bin"
OPENDOG_BIN="$USER_BIN/opendog"
SHELL_NAME="$(basename "${SHELL:-}")"
if [[ "$PYTHON_BIN" = /* ]]; then
  PYTHON_SHEBANG="$PYTHON_BIN"
else
  PYTHON_SHEBANG="/usr/bin/env $PYTHON_BIN"
fi

cd "$PROJECT_ROOT"

"$PYTHON_BIN" -m pip install --user \
  "litellm>=1.56.0" \
  "openai>=1.30.0" \
  "pydantic>=2.8.0" \
  "python-dotenv>=1.0.0" \
  "prompt-toolkit>=3.0.48" \
  "pyyaml>=6.0.2" \
  "rich>=13.9.0" \
  "typer>=0.12.5" \
  "lark-oapi>=1.4.0"

mkdir -p "$USER_BIN"
cat > "$OPENDOG_BIN" <<EOF
#!$PYTHON_SHEBANG
import os
import sys

PROJECT_ROOT = "$PROJECT_ROOT"

sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
os.environ.setdefault("OPENDOG_DEFAULT_WORKSPACE", os.path.join(PROJECT_ROOT, "workspace"))

from opendog.cli.main import app

if __name__ == "__main__":
    app()
EOF
chmod +x "$OPENDOG_BIN"

LINK_TARGET=""
for candidate in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
  if [ -d "$candidate" ] && [ -w "$candidate" ]; then
    LINK_TARGET="$candidate/opendog"
    break
  fi
done

if [ -n "$LINK_TARGET" ] && [ -x "$OPENDOG_BIN" ]; then
  ln -sf "$OPENDOG_BIN" "$LINK_TARGET"
fi

case "$SHELL_NAME" in
  zsh)
    SHELL_RC="$HOME/.zshrc"
    ;;
  bash)
    SHELL_RC="$HOME/.bashrc"
    ;;
  *)
    SHELL_RC="$HOME/.profile"
    ;;
esac

touch "$SHELL_RC"

if ! grep -F "$USER_BIN" "$SHELL_RC" >/dev/null 2>&1; then
  {
    echo ""
    echo "# opendog CLI"
    echo "export PATH=\"$USER_BIN:\$PATH\""
  } >> "$SHELL_RC"
fi

echo "opendog installed."
if command -v opendog >/dev/null 2>&1; then
  echo "Command available at: $(command -v opendog)"
else
  echo "Restart your terminal, or run:"
  echo "source $SHELL_RC"
fi
echo ""
echo "Start with:"
echo "opendog"
