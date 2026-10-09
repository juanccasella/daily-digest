# Spec · Reporte diario cruzando sistemas reales (P0)

> Flujo `flujo-construir`, tamaño **grande** (fuentes externas, LLM, entrada no confiable). Ejecución de una pasada: este archivo reemplaza el Gate 1. Gate 2 (commit/push/publicación) se mantiene.

## Intent
Cada mañana quiero un informe que cruce **Jira, calendario, mails y chats de Teams reales** y me diga **qué avancé ayer, en qué ayudó a mis objetivos y qué sigue hoy**, sin copiar nada a mano y sin que el LLM invente: cada afirmación cita un id real que el código verifica.

## Criterios de aceptación (verificables)
| # | Criterio | Cómo se verifica |
|---|---|---|
| A1 | Fuentes: Jira abiertos + **cambios de la ventana** (transiciones y comentarios vía changelog), calendario de la ventana y del día, mails (`/me/messages`, `$select` mínimo), chats (`Chat.Read`). Cada ítem tiene id citable: `jira:KEY`, `cal:<8hex>`, `mail:<8hex>`, `chat:<8hex>` | tests de parseo con payloads de ejemplo; prueba de integración marcada `integration` |
| A2 | Si una fuente está bloqueada (403) o falla, el informe **sigue** y muestra un aviso explícito; chats cae al export (`_local-only/` o `fixtures/`) | eval `chat-bloqueado`, `fuente-caida` |
| A3 | Plan B aprobado en Prompt 1: fuentes M365 vía conector MCP (`claude -p`, solo herramientas de lectura del conector) y modelo vía `claude -p` aislado (`--safe-mode --tools "" --strict-mcp-config`), detrás de la misma interfaz | tests de parseo/armado de comando; prueba de integración marcada |
| A4 | Ventana "ayer" = día laboral anterior (lunes → viernes); `--desde/--hasta` la pisan | tests de `previous_workday` |
| A5 | Objetivos desde `_local-only/goals.md` o `fixtures/goals.md`; ids `goal:N` (explícitos `[goal:N]` o numerados en orden) | tests de parseo |
| A6 | Agentes LLM: (a) lector aislado de mails/chats (sin tools, datos delimitados, salida JSON con citas), (b) vinculador de objetivos, (c) planificador. Traer datos y criticar es **código** | revisión del grafo + evals |
| A7 | Informe en 3 secciones **Avanzó / Ayudó a objetivos / Sigue**; cada afirmación cita ids reales | `validate_report` en cada eval |
| A8 | Validador: toda cita existe; toda afirmación tiene ≥1 cita; todo `goal:` citado existe; afirmaciones sin URLs/links/imágenes (canal de exfiltración). Falla → feedback al agente (máx. 3 intentos) → respaldo heurístico **avisado** | evals `cita-inventada`, `sin-cita`, `goal-inexistente`, `no-converge` |
| A9 | Sin canal de salida: solo lee y escribe archivos locales; mails/chats delimitados como no confiables; mail malicioso que intenta exfiltrar no se obedece (ni con un modelo "comprometido") | evals `inyeccion-*` + test de que no hay HTTP en modo offline |
| A10 | Golden dataset ≥ 25 casos en `evals/golden/`, runner `scripts/run_evals.py` con tasa de aciertos, offline con LLM simulado determinístico; `--real` opcional | `python scripts/run_evals.py` |
| A11 | Traza JSONL por corrida en `_local-only/traces/`: span por nodo y por llamada al modelo (modelo, tokens, latencia, costo estimado) | test de traza |
| A12 | Harness: `CLAUDE.md` corto, `docs/harness.md`, `scripts/validar.py` (tests + evals + secretos sobre `git ls-files` + estructura), hook pre-push `#!/bin/sh`, CI con el mismo validador | `python scripts/validar.py` |
| A13 | 4 ADRs en `docs/adr/`; README final con diagrama, offline/real, "cuándo NO usar IA", resultados de evals, límites | revisión |
| A14 | `daily-digest --offline --no-llm` funciona sin credenciales; ids de modelo desde `DIGEST_MODEL` | smoke test |

## Fuera de alcance (P1/P2, siguiente iteración)
Memoria entre días (SQLite), MCP propio, skill `daily-digest`, entrega (`flujo-entrega-proyecto`), app registration de Graph con refresh token.

## Decisiones (→ ADRs)
1. **LangGraph** como orquestador (fan-out de fuentes en paralelo, ciclo crítico→agente explícito, trazable).
2. **Código vs LLM:** traer datos, ventana, "qué se movió en Jira", reuniones y crítica = código. LLM solo donde hay lenguaje: resumir mails/chats, vincular trabajo↔objetivo, priorizar.
3. **Cuarentena de entrada no confiable:** el lector no tiene tools, recibe los mensajes delimitados (`<datos_no_confiables>` + id por mensaje + marca en cada línea) y devuelve JSON; su salida pasa por el validador antes de llegar a otro agente. El resto de los agentes **nunca** ve el texto crudo de mails/chats, solo las afirmaciones validadas.
4. **Token de Graph de corta vida** (Graph Explorer, ~1 h) + plan B por conector M365 porque el tenant exige aprobación de administrador para Graph Explorer.

## Decisiones abiertas / limitaciones conocidas
- El tenant corporativo exige **aprobación de administrador** para Graph Explorer (verificado el 09/10): sin `GRAPH_ACCESS_TOKEN`. Mails/calendario/chats reales van por el conector M365 (plan B, verificado: calendario, mail y chats OK).
- Sin `ANTHROPIC_API_KEY`: el modelo real va por `claude -p` (verificado).
- Objetivos reales: el sprint activo no tiene Sprint Goal y el proyecto no tiene épicas abiertas (verificado vía API) → sigue el `goals.md` provisorio.
- El conector Atlassian Rovo responde 403 ("app not installed") en el sitio; la API REST de Jira funciona.

## Plan (tareas ≤ 15 min, en orden; riesgo dominante entre paréntesis)
1. Modelos nuevos (`Message`, `JiraChange`, `Goal`, `Claim`, `Link`) + ids citables estables (colisiones).
2. Ventana "ayer" + CLI `--desde/--hasta` (fin de semana).
3. Objetivos: parser `goals.md` + `fixtures/goals.md` (formatos mixtos).
4. Fixtures: mails, chats, cambios de Jira, mail malicioso (realismo ficticio).
5. Evals primero: golden dataset ≥ 25 casos + runner + LLM simulado (casos que no prueban nada).
6. Validador extendido `validate_report` (falsos negativos).
7. Capa LLM: interfaz `LLM` con backends `anthropic`, `claude-cli`, `fake`; spans (aislamiento del CLI).
8. Agentes: lector aislado, vinculador, planificador con crítico y respaldo (feedback mal formado).
9. Fuentes reales: Jira changelog, Graph mail/chats/calendario, adaptador M365 vía `claude -p`, export de chats (403 / formatos).
10. Grafo LangGraph: fan-out de 5 fuentes + agentes + render 3 secciones (estado concurrente).
11. Trazas JSONL (propagación de contexto entre hilos).
12. Seguridad: test de no-HTTP offline + revisión `revisor-seguridad-agentes`.
13. Harness: `CLAUDE.md`, `docs/harness.md`, `scripts/validar.py`, hook, CI.
14. ADRs + README.
15. Revisión en paralelo + `verificar-entrega`.
