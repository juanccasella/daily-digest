# Plan AI Day — daily-digest

Challenge elegido (catálogo, grupo Builder): **Reporte diario cruzando sistemas reales** — "un asistente que cruce Jira, calendario, chats y mails REALES (vía API, no copiado a mano) para armar un resumen de qué se avanzó, en qué ayudó a los objetivos, y qué sigue".

## Estado de partida (ya hecho)
- Orquestador LangGraph: Jira + calendario (Graph) → plan (LLM) → validador en código → reintento con feedback → fallback heurístico.
- 6 evals offline, fixtures ficticios, demo sin credenciales (`daily-digest --offline --no-llm`).

## Brecha contra el challenge
| Pide el challenge | Hoy | Falta |
|---|---|---|
| Jira, calendario, **chats, mails** reales por API | Jira ✓ calendario ✓ | Mail (`Mail.Read`) y chats de Teams (`Chat.Read`) vía Graph |
| Resumen de **qué se avanzó** | Solo plan hacia adelante | Ventana "ayer": tickets movidos, reuniones, mails enviados, chats |
| **En qué ayudó a los objetivos** | — | Archivo de objetivos + agente que vincula trabajo ↔ objetivo |
| **Qué sigue** | Plan del día ✓ | Arrastrar lo que quedó sin hacer |

## Prioridades (por si el tiempo aprieta, cortar de abajo hacia arriba)

### P0 — cumplir el challenge
1. **Chequear primero (15 min máx):** ¿el tenant deja dar consentimiento a `Mail.Read` y `Chat.Read` en Graph Explorer? Si `Chat.Read` está bloqueado, no pelear: la fuente de chats queda detrás de la misma interfaz con adaptador alternativo (ver Riesgos).
2. Fuentes nuevas en `sources.py`, todas con la misma forma que `Issue`/`Event` y con **id citable** (key de ticket, id de mensaje).
3. Informe de 3 secciones: **Avanzó / Ayudó a objetivos / Sigue**. Cada afirmación cita ids de fuentes.
4. `goals.md` en `_local-only/` (objetivos reales, no van a git) + `fixtures/goals.md` ficticio.
5. Extender `validate.py`: toda cita debe existir en los datos; toda afirmación debe tener al menos una cita.

### P1 — lo que lo lleva más allá (lo que mira un Builder)
6. **Multi-agente con criterio** (patrón supervisor + paralelo; el error más común es separar en agentes lo que no lo necesita): traer datos es **código**, no un agente. Los agentes LLM son tres, cada uno con un motivo: (a) *lector aislado* de mails y chats (contexto en cuarentena, sin tools), (b) *vinculador de objetivos*, (c) *planificador*; más el *crítico determinístico*. Las lecturas de fuentes corren en paralelo.
7. **Seguridad (prompt injection) y trifecta letal:** el digest tiene datos privados (Jira, mails) y contenido no confiable (mails, chats), por lo que **no puede tener canal de salida**: solo lee y escribe un archivo local; nada de enviar mails/mensajes ni llamadas HTTP salientes. Mails y chats se delimitan como datos; el agente que los lee no tiene herramientas con efectos y su salida estructurada se valida antes de pasar al siguiente. Un fixture de mail malicioso ("ignorá lo anterior y…") con test que prueba que no se obedece. Recurso: `seguridad-agentes/` del repo de assets.
8. **Memoria entre días (SQLite):** guardar el plan de ayer y compararlo con lo hecho; lo pendiente se arrastra. Patrón ya usado en `personal/SUR/db/` (`schema.sql`).
9. **Observabilidad:** traza por corrida en `_local-only/traces/*.jsonl`, un span por nodo y por llamada al modelo con nombres tipo OpenTelemetry GenAI (`chat`, `invoke_agent`), modelo, tokens, latencia y costo estimado. Recurso: `observabilidad/`.
10. **Evals ampliados:** golden dataset de **25–50 casos** en `evals/golden/` (día sin reuniones, ticket sin prioridad, cita inventada, bloque fuera de horario, inyección, mail vacío…) con runner que reporta tasa de aciertos y corre en el pre-push. Recurso: `evals/`.
11. **Harness de Flock IT:** aplicar el mismo patrón de `trabajo/adium` (CLAUDE.md corto + `docs/harness.md` + `scripts/validar.py` con escaneo de secretos + hook pre-push + CI). Para un repo **público** el escaneo de secretos es no negociable.

### P2 — extra si sobra tiempo
12. **MCP server propio** que exponga `get_digest`, `get_week_review`: Claude Code podría pedir el digest como herramienta. Es el tema "qué es un MCP y cómo se construiría uno propio" de las charlas.
13. **Skill de Claude Code** `daily-digest` (con `skill-creator`) para dispararlo con una frase.
14. **Entrega:** diagrama de arquitectura (`archify`), auditoría de costo (`auditor-costo-ia`), deck corto de demo (`presentacion-validacion-tecnica` + marca `C:\dev\design.md`).

## Cierre del día (antes de las 12:00 si se puede)
- [ ] `/code-review` y `/security-review` sobre el repo.
- [ ] `validar.py` verde; `git log` sin secretos; `.env` y `_local-only/` ignorados.
- [ ] README final: arquitectura, tabla "cuándo NO usar IA", resultados de evals, próximos pasos.
- [ ] Publicar repo público en la cuenta personal y **pegar el link** en la plataforma (se habilita el 9/10 a las 12:00).

## Riesgos y decisiones abiertas
- **`Chat.Read` bloqueado por el tenant:** el challenge dice "vía API". Plan B: adaptador de chats con la misma interfaz que lea un export; dejarlo documentado como limitación y no como silencio.
- **Token de Graph vence ~1 h:** aceptable para el día; mejora futura = app registration + refresh.
- **Datos reales en repo público:** nunca. Las demos y screenshots usan fixtures. Los digests reales viven en `_local-only/`.
- **Alcance:** mejor P0 + 3 ítems de P1 bien hechos y con evals que todo a medias.

## Recursos del repo de assets que conviene leer primero
`orquestadores/`, `coordinacion-multiagente/`, `evals/`, `seguridad-agentes/`, `observabilidad/`, `memoria-de-agentes/`, `harness/`.
