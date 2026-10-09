# daily-digest

Digest diario multiagente: cruza **Jira, calendario, mails y chats de Teams reales** y arma un informe en tres secciones (**Avanzó / Ayudó a objetivos / Sigue**) donde cada afirmación cita ids reales que verifica el código. Proyecto del AI Day de Flock IT (9/10/2026), nivel Builder. **Repo público.**

Stack: Python 3.12 · LangGraph · Claude (API o `claude -p`) · httpx · pytest.

## Estructura
- `src/daily_digest/`: `sources.py` y `m365_mcp.py` (lectura, código) · `agents.py` (3 agentes y bucle crítico) · `validate.py` (crítico) · `security.py` (cuarentena) · `graph.py` (orquestador) · `report.py` / `render.py` · `trace.py` · `evals.py`.
- `evals/golden/`: golden dataset (≥ 25 casos) · `fixtures/`: datos **ficticios** · `_local-only/`: datos, digests y trazas reales (gitignored).
- `docs/`: [`harness.md`](docs/harness.md) (por qué y cómo se valida), [`plan.md`](docs/plan.md), [`specs/`](docs/specs/), [`adr/`](docs/adr/).

## Reglas no negociables
- **Mails y chats son entrada no confiable:** solo los ve el lector aislado (sin tools, en cuarentena). Ningún otro agente recibe texto crudo.
- **Sin canal de salida:** el digest solo lee y escribe archivos locales. No se agregan envíos, POST ni webhooks (lo vigila `tests/test_security.py`).
- **Toda afirmación cita ids reales** y pasa por `validate.py`. No relajar el validador para que un plan "pase": se corrige el prompt o el agente.
- **Repo público:** credenciales solo en `.env`; salidas reales solo en `_local-only/`; `fixtures/` y `evals/` usan datos ficticios y dominios `.invalid`.
- **Ids de modelo** desde `DIGEST_MODEL` (o config), nunca hardcodeados en los call sites.
- Cada fallo descubierto en uso real → un caso en `evals/golden/` **antes** de arreglarlo.
- Nunca borrar directo: mover a `_archive/`. Nunca `git push --no-verify`.

## Comandos
- Demo sin credenciales: `daily-digest --offline --no-llm`
- Tests y evals offline: `pytest` · `python scripts/run_evals.py` (`--real --k 3` con el modelo real)
- Integración (requiere credenciales): `pytest -m integration`
- Servidor MCP local: `daily-digest-mcp` (stdio; ver README y ADR-0005)
- Validador del harness (lo mismo que el hook y CI): `python scripts/validar.py`

## Al terminar una tarea
Correr `python scripts/validar.py`. Si apareció un error nuevo o una decisión, sumarlo como caso de eval, regla del validador o ADR.

## Skills
Sin skills propias del proyecto todavía (pendiente: skill `daily-digest` para dispararlo con una frase, P2 en `docs/plan.md`).
