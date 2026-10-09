# Harness de daily-digest

> No confiás en la IA: confiás en el harness.

El harness es lo que hace que un cambio hecho con IA (o por una persona) sea seguro de publicar: **instrucciones + validación local + validación remota + planificación**. Sigue el patrón del equipo, adaptado a un repo Python **público**.

## 1. Qué problema resuelve
- El repo es público: un secreto o un dato real publicado no se puede despublicar.
- El sistema usa LLM: sin evals, "probé a mano" no alcanza y las regresiones pasan inadvertidas.
- El mismo modelo escribe y revisa, y comparten puntos ciegos: las reglas tienen que estar en código, no en la memoria de nadie.

## 2. Estructura
```
CLAUDE.md                 # corto: qué es, reglas no negociables, comandos
docs/harness.md           # este archivo: el porqué de cada validación
docs/specs/               # intent → criterios → plan (una por feature)
docs/adr/                 # decisiones de arquitectura
evals/golden/*.json       # golden dataset (≥ 25 casos), grader 100 % código
scripts/validar.py        # validador único: hook pre-push + CI
scripts/instalar-hooks.sh # instala el pre-push (#!/bin/sh)
.github/workflows/ci.yml  # corre el mismo validador
fixtures/                 # datos ficticios (dominios .invalid)
_local-only/              # datos reales, digests y trazas (gitignored)
```

## 3. Las cuatro capas
| Capa | Dónde | Qué frena |
|---|---|---|
| Instrucciones | `CLAUDE.md`, ADRs | Que un agente (o una persona) rompa las reglas por no conocerlas |
| Hook local | `.git/hooks/pre-push` → `scripts/validar.py` | Pushear secretos, datos reales o código con evals en rojo |
| CI | `.github/workflows/ci.yml` → `scripts/validar.py` | Lo mismo, aunque alguien saltee el hook |
| Planificación | `docs/specs/` (spec-driven) + gates humanos | Construir sin criterios verificables; commitear sin revisión |

### Qué valida `scripts/validar.py`
1. **Estructura:** existen `CLAUDE.md`, `README.md`, `docs/harness.md`, `.env.example`, `ci.yml`, etc.; ≥ 25 casos golden y 4 ADRs.
2. **Ignorados:** `.gitignore` cubre `.env`, `_local-only/` y `.claude/settings.local.json`.
3. **Archivos privados:** ningún `.env` ni `_local-only/` entre lo que se publicaría (`git ls-files --cached --others --exclude-standard`).
4. **Secretos:** regex sobre todo lo publicable: tokens Bearer, claves de Anthropic (`sk-ant-`), Atlassian (`ATATT3`), GitHub, AWS, JWT (tokens de Graph), claves privadas y asignaciones `*_TOKEN=valor`.
5. **Datos ficticios:** en `fixtures/` y `evals/`, todo mail usa dominios reservados (`.invalid`, `example`). Un dominio real es probablemente un dato real.
6. **Tests offline** (`pytest`) y **golden dataset** (`scripts/run_evals.py`, LLM simulado determinístico).

Sale con 1 ante cualquier ERROR; los AVISOS no bloquean. `--rapido` omite tests y evals.

## 4. Evals y seguridad como parte del harness
- **Golden dataset**: regresión, bordes, fuentes degradadas, crítico (cada modo de falla de cada agente) y seguridad (inyección, cuarentena, enlaces de exfiltración).
- **LLM simulado** (`fake_llm.py`): por defecto se porta bien, y cada caso puede programar respuestas malas o "comprometidas". Así se prueba que **el código** frena al modelo, no que el modelo se porte bien.
- **Prueba de mutación** (manual, una vez por cambio grande): romper una defensa (aceptar URLs, no escapar delimitadores, pasar texto crudo al vinculador, no verificar citas) tiene que poner al menos un caso en rojo. Verificado el 09/10.
- `pytest -m llm` y `run_evals.py --real --k 3` corren contra el modelo real (pass@k / pass^k).

## 5. Optimización de tokens y costo
- Cada llamada al modelo queda en `_local-only/traces/*.jsonl`, con tokens, latencia y costo (`gen_ai.usage.*`, `digest.cost_usd`).
- El plan B de M365 por conector es el mayor costo (~USD 1,2 por corrida): con un token de Graph pasa a centavos.
- El lector por `claude -p` corre con `--safe-mode --tools "" --strict-mcp-config` (~800 tokens de base, sin CLAUDE.md ni skills).

## 6. Cómo evoluciona
Cada error que se escapa se vuelve una regla nueva: un caso en `evals/golden/`, una regla de `validate.py` o un patrón de `validar.py`. Ejemplos del 09/10:
- la regla de plan vacío (`39-planner-plan-vacio`);
- las respuestas que no son objetos;
- las imágenes `<img>` y `![a][r]`;
- el shim `claude.CMD`.

Todos salieron de las revisiones (`cazador-fallas-silenciosas`, `revisor-seguridad-agentes`, `/code-review`) o del uso real. Nunca `--no-verify`.

## 7. Convenciones
- Identificadores en inglés; textos al usuario, docs y mensajes del validador en español.
- Cambios chicos y verificables (~15 min), con su test o eval.
- Commits: Conventional Commits + gitmoji en inglés (`✨ feat(sources): ...`).
- Instalar el hook después de clonar: `sh scripts/instalar-hooks.sh`.
