# ADR-0004: Token de Graph de corta vida, con plan B por el conector M365
**Fecha:** 2026-10-09 · **Estado:** aceptada · **Quiénes:** Juan Cruz Casella (con Claude Code)

## Contexto
El desafío pide mails, calendario y chats reales "vía API". La vía directa es Microsoft Graph con `Mail.Read`, `Calendars.Read` y `Chat.Read`. Registrar una app propia en Entra (con refresh token) requiere permisos de administrador. El 09/10 verificamos que el tenant corporativo exige **aprobación de administrador incluso para Graph Explorer**, así que hoy no hay token. En cambio, el conector Microsoft 365 de Claude ya está autorizado para el usuario, con esos mismos permisos concedidos (solo lectura).

## Decisión
Usamos dos adaptadores detrás de la misma interfaz `Sources`:
1. **Graph directo** con `GRAPH_ACCESS_TOKEN` de corta vida (~1 h, de Graph Explorer) cuando exista.
2. **Plan B: el conector M365 vía `claude -p`.** Se usa cuando no hay token, con `--fuentes-m365 auto` como valor por defecto. Restricciones:
   - Cada consulta habilita solo las tools de lectura exactas que necesita (`outlook_email_search`, `outlook_calendar_search`, `teams_list_chats`, `chat_message_search`, `read_resource`); un test exige que ninguna tenga un verbo de escritura.
   - Built-ins denegadas.
   - `--max-turns 8`.
   - Sin configuración ni credenciales del usuario en el entorno.
   - Respuesta validada por esquema, ids y ventana en código.

Si un endpoint de chats responde 403, se usa un export local (`_local-only/chats-export.json`) y el informe lo avisa.

## Alternativas consideradas
- **App registration con refresh token:** la solución correcta a futuro, pero bloqueada por permisos de administrador.
- **Copiar mails o chats a mano:** el desafío lo descarta explícitamente.
- **Abandonar mails y chats:** incumpliría el desafío.

## Consecuencias
+ El desafío se cumple con datos reales hoy, sin pedir nada a un administrador, y los dos caminos comparten parsers, ids citables y evals.
− **Costo y latencia.** El plan B es agéntico: medido el 09/10, USD 0,74 a 1,2 por corrida completa y 1,5 a 2 minutos, contra centavos con Graph. Queda en la traza (`execute_tool m365.*`).
− El token de Graph Explorer vence en ~1 h: sirve para la demo, no para un uso diario desatendido.
! **Un LLM con tools lee contenido no confiable** (ver ADR-0003). Mitigación: el conector no tiene tools de escritura ni de envío; la salida es JSON validado y su texto vuelve a entrar como no confiable al lector en cuarentena.
! En Windows, el shim `claude.CMD` truncaba los argumentos multilínea y anulaba en silencio `--tools` y `--output-format`. Se resolvió llamando al `claude.exe` nativo, con test de regresión.
