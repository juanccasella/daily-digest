"""Validador del harness: lo mismo corre en el hook pre-push y en CI.

    python scripts/validar.py            # todo: estructura, secretos, datos ficticios, tests y evals
    python scripts/validar.py --rapido   # sin tests ni evals (solo chequeos estáticos)

Sale con 1 si hay al menos un ERROR (los AVISOS no bloquean). Solo stdlib + el venv del proyecto.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

REQUERIDOS = ["CLAUDE.md", "README.md", ".gitignore", ".env.example", "pyproject.toml", "docs/harness.md",
              "docs/plan.md", "scripts/run_evals.py", ".github/workflows/ci.yml"]
IGNORADOS = [".env", "_local-only/", ".claude/settings.local.json"]
MIN_GOLDEN, MIN_ADR = 25, 4

SECRETOS = re.compile("|".join([
    r"Bearer\s+[A-Za-z0-9._\-]{20,}",
    r"client_secret[\"']?\s*[:=]\s*[\"'][^\"']{16,}",
    r"api[_-]?key[\"']?\s*[:=]\s*[\"'][^\"']{16,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY",
    r"sk-ant-[A-Za-z0-9_\-]{20,}",                        # Anthropic
    r"ATATT3[A-Za-z0-9_\-=]{20,}",                        # Atlassian API token
    r"gh[pousr]_[A-Za-z0-9]{30,}",                         # GitHub
    r"AKIA[0-9A-Z]{16}",                                   # AWS
    r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.",   # JWT (p. ej. token de Graph)
    r"(ANTHROPIC_API_KEY|JIRA_API_TOKEN|GRAPH_ACCESS_TOKEN)\s*=\s*[^\s#]{8,}",
]), re.I)
# Datos de ejemplo: los mails de fixtures/evals deben usar dominios reservados (.invalid / example).
MAIL = re.compile(r"[\w.+-]+@([\w-]+\.)+[\w-]+")
DOMINIO_OK = re.compile(r"@([\w-]+\.)*(invalid|example|example\.com|ejemplo\.invalid)$", re.I)
BINARIOS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".zip", ".pyc", ".docx", ".xlsx"}


def archivos_a_publicar() -> list[Path]:
    """Lo que entraría en un commit: versionados + no ignorados."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                             cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(f"  ERROR  git: no se pudo listar los archivos a publicar ({e}). ¿Es un checkout de git?")
    return [RAIZ / p for p in out.splitlines() if p and (RAIZ / p).is_file()]


def chequear_estatico(avisos: list, errores: list) -> int:
    for rel in REQUERIDOS:
        if not (RAIZ / rel).exists():
            errores.append((rel, "falta archivo requerido por el harness"))
    gi = (RAIZ / ".gitignore").read_text(encoding="utf-8") if (RAIZ / ".gitignore").exists() else ""
    for pat in IGNORADOS:
        if pat not in gi:
            errores.append((".gitignore", f"no ignora {pat}"))
    golden = list((RAIZ / "evals" / "golden").glob("*.json"))
    if len(golden) < MIN_GOLDEN:
        errores.append(("evals/golden", f"{len(golden)} casos (< {MIN_GOLDEN})"))
    adrs = list((RAIZ / "docs" / "adr").glob("[0-9]*.md"))
    if len(adrs) < MIN_ADR:
        avisos.append(("docs/adr", f"{len(adrs)} ADRs (se esperan {MIN_ADR})"))
    claude_md = RAIZ / "CLAUDE.md"
    if claude_md.exists() and len(claude_md.read_text(encoding="utf-8").splitlines()) > 80:
        avisos.append(("CLAUDE.md", "más de 80 líneas: mover detalle a docs/"))

    archivos = archivos_a_publicar()
    for f in archivos:
        rel = f.relative_to(RAIZ).as_posix()
        if rel == ".env" or rel.startswith("_local-only/"):
            errores.append((rel, "archivo privado a punto de publicarse"))
            continue
        if f.suffix.lower() in BINARIOS:
            avisos.append((rel, "binario a publicar: no se escanea, revisalo a mano"))
            continue
        try:
            texto = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            errores.append((rel, "no se puede leer como UTF-8: no se puede escanear (convertilo o ignoralo)"))
            continue
        for n, linea in enumerate(texto.splitlines(), 1):
            if SECRETOS.search(linea):
                errores.append((f"{rel}:{n}", "posible secreto"))
        if rel.startswith(("fixtures/", "evals/")):
            for m in MAIL.finditer(texto):
                if not DOMINIO_OK.search(m.group(0)):
                    errores.append((rel, f"mail con dominio no reservado ({m.group(0).split('@')[1]}): ¿dato real?"))
    return len(archivos)


def correr(cmd: list[str], nombre: str, errores: list) -> None:
    print(f"→ {nombre}…", flush=True)
    p = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace")
    resumen = (p.stdout.strip().splitlines() or [""])[-1]
    print(f"  {resumen}")
    if p.returncode != 0:
        errores.append((nombre, f"falló (código {p.returncode}): {resumen or p.stderr.strip()[-200:]}"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true", help="omitir tests y evals")
    a = ap.parse_args()

    avisos: list = []
    errores: list = []
    n = chequear_estatico(avisos, errores)
    print(f"Harness daily-digest · archivos a publicar revisados: {n}")
    if not a.rapido:
        correr([sys.executable, "-m", "pytest", "-q"], "tests offline (pytest)", errores)
        correr([sys.executable, "scripts/run_evals.py"], "golden dataset (run_evals)", errores)

    for ruta, msg in avisos:
        print(f"  AVISO  {ruta}: {msg}")
    for ruta, msg in errores:
        print(f"  ERROR  {ruta}: {msg}")
    if errores:
        print(f"✗ {len(errores)} error(es). No se puede pushear.")
        return 1
    print(f"✓ Sin errores ({len(avisos)} aviso/s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
