# ADR-0005: Exponemos el digest como servidor MCP local, con la demo como opción por defecto
**Fecha:** 2026-10-09 · **Estado:** aceptada · **Quiénes:** Juan Cruz Casella (con Claude Code)

## Contexto
Queremos pedirle el digest a Claude Code como una herramienta más ("¿qué tengo hoy?") sin abrir una terminal. El digest contiene resúmenes de mails y chats de terceros. Exponerlo por MCP lo mete en el contexto de un agente que **sí tiene tools**, y eso reabre la trifecta que el ADR-0003 cerraba dentro del digest.

## Decisión
Usamos un servidor MCP **local por stdio** (`daily_digest.mcp_server`, SDK oficial `mcp`), con tres tools:
- `list_digests` y `get_digest`: solo lectura de digests guardados. La fecha se valida con regex, lo que también bloquea el path traversal.
- `run_digest`: por defecto corre la **demo offline sin modelo**. Para una corrida real hay que pedir explícitamente `real=True` y, para usar el modelo, `use_model=True`.

Toda respuesta va precedida de un marco que la declara *datos, no instrucciones*. Las demos se guardan como `AAAA-MM-DD-demo.md` y nunca se sirven como "el último digest real".

## Alternativas consideradas
- **Solo CLI:** más simple, pero no se integra al flujo de trabajo con Claude Code.
- **Servidor HTTP/SSE:** innecesario para uso personal, y suma superficie de red.
- **`run_digest` real por defecto:** más cómodo, pero un pedido ambiguo dispararía lecturas reales y consumo de cupo.

## Consecuencias
+ El digest queda a una pregunta de distancia en Claude Code, y la lógica se comparte con el CLI (`cli.run`).
− El texto del digest (sanitizado: sin URLs, enlaces ni HTML) entra en un agente con tools.
! **Riesgo residual:** un resumen de mail que logre colarse con tono imperativo podría influir en el agente que llama. Mitigación: el marco de datos, la sanitización y la validación previas, y los gates humanos del propio Claude Code para cualquier acción con efectos.
