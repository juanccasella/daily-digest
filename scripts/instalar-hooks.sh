#!/bin/sh
# Instala el hook pre-push que corre el mismo validador que CI.
# Uso: sh scripts/instalar-hooks.sh
# Shebang /bin/sh a propósito: /usr/bin/env bash puede resolver a WSL en Windows.
set -e
RAIZ="$(git rev-parse --show-toplevel)"
HOOK="$RAIZ/.git/hooks/pre-push"
cat > "$HOOK" <<'EOF'
#!/bin/sh
RAIZ="$(git rev-parse --show-toplevel)"
if [ -x "$RAIZ/.venv/Scripts/python.exe" ]; then PY="$RAIZ/.venv/Scripts/python.exe"
elif [ -x "$RAIZ/.venv/bin/python" ]; then PY="$RAIZ/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then PY=python3
else PY=python; fi
echo "→ Validando harness de daily-digest (tests, evals, secretos)..."
"$PY" "$RAIZ/scripts/validar.py" || exit 1
EOF
chmod +x "$HOOK"
echo "Hook pre-push instalado en $HOOK"
