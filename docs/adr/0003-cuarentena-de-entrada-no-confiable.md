# ADR-0003: Mails y chats en cuarentena: lector aislado sin tools y sin canal de salida
**Fecha:** 2026-10-09 · **Estado:** propuesta · **Quiénes:** Juan Cruz Casella (con Claude Code)

## Contexto
El digest cumple dos de las tres patas de la "trifecta letal" (Willison): accede a datos privados (Jira, mails, objetivos) y lee contenido no confiable (mails y chats de terceros). La prompt injection no tiene parche (OWASP LLM01): hay que diseñar asumiendo que va a ocurrir. La tercera pata, un canal de salida, es la que hay que eliminar.

## Decisión
- **Sin canal de salida.** El digest solo lee fuentes y escribe archivos locales; no tiene llamadas HTTP de escritura ni envío de mails o mensajes. Lo vigilan `tests/test_security.py`, que busca en el código `.post(`, `sendMail`, `smtplib`, etc., y un test que corta la red en modo offline.
- **Cuarentena.** Solo el lector (a) ve el texto de mails y chats.
  - El lector no tiene tools.
  - Los mensajes llegan dentro de `<datos_no_confiables>`, con `<` y `>` escapados (no se puede cerrar ni falsificar el bloque) y cada línea marcada con `│`.
- **Salida estructurada y validada.** El lector devuelve JSON. Las afirmaciones pasan por código antes de llegar a otro agente: citas existentes y solo de `mail:`/`chat:`, citas inline verificadas, sin URLs ni enlaces markdown (canal de exfiltración por imágenes), largo acotado.
- **Aislamiento del resto.** El vinculador y el planificador nunca ven el texto crudo (lo verifica el eval `cuarentena-solo-el-lector-ve-crudo`).
- **Señal para el humano.** Los mensajes con patrones de inyección se avisan en el informe.

## Alternativas consideradas
- **Filtrar las inyecciones por regex y descartar el mensaje:** la detección siempre es incompleta. Se usa solo como aviso, nunca como única defensa.
- **Un agente con tools que lea y actúe:** cumpliría las tres patas de la trifecta.
- **Dual LLM / CaMeL completo:** más fuerte, pero excesivo para un digest sin acciones. La validación en código cumple el rol de "LLM privilegiado".

## Consecuencias
+ Un modelo comprometido no puede exfiltrar datos (no hay salida), ni inventar citas o enlaces (el crítico lo rechaza). Lo prueba `inyeccion-modelo-obediente`.
− El lector puede omitir o resumir mal; eso es calidad, no seguridad.
! **Riesgo residual 1:** un texto validado del lector llega al vinculador, y una inyección podría sesgar un vínculo. Mitigación: el vinculador tampoco tiene tools y su salida también se valida.
! **Riesgo residual 2:** el plan B de M365 (ADR-0004) es un LLM con tools de lectura sobre contenido no confiable. Mitigación: lista exacta de tools de lectura por consulta, verificada por test; built-ins denegadas; sin credenciales en su entorno; salida validada por esquema en código.
! **Riesgo residual 3:** los títulos de tickets y los asuntos de reuniones también los escriben terceros, y llegan (sanitizados) al vinculador y al planificador. Mitigación: se etiquetan como texto de terceros, se buscan señales de inyección y la salida de esos agentes se valida igual.
+ **Lo encontró la revisión del 09/10 y quedó con test:** el respaldo del lector ya no pasa texto de terceros al vinculador; el render neutraliza enlaces, `<img>` y `![a][r]`; los subprocess no heredan credenciales.
