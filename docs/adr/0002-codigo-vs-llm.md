# ADR-0002: Traer datos y criticar es código; el LLM solo donde hay lenguaje
**Fecha:** 2026-10-09 · **Estado:** aceptada · **Quiénes:** Juan Cruz Casella (con Claude Code)

## Contexto
El error más común en sistemas multiagente es convertir en agente lo que es una consulta o una regla. Cada salto LLM suma costo, latencia y riesgo de alucinación. El desafío exige además que el informe se apoye en datos reales y verificables.

## Decisión
Es **código**: leer las fuentes, calcular la ventana "ayer", derivar qué se movió en Jira (transiciones y comentarios desde el changelog), listar las reuniones, detectar señales de inyección, validar y renderizar.
Es **LLM**, con tres agentes y un motivo cada uno:
- (a) lector aislado: resumir mails y chats en lenguaje natural.
- (b) vinculador: relacionar el avance con objetivos escritos en prosa.
- (c) planificador: priorizar con criterio.

Cada agente tiene un respaldo heurístico y un crítico determinístico. Tras 3 intentos fallidos se usa el respaldo, y el informe lo avisa.

## Alternativas consideradas
- **LLM para "qué se avanzó" en Jira:** innecesario. El changelog ya es estructurado, y un LLM podría inventar transiciones.
- **LLM como juez del informe:** más caro y menos confiable que reglas exactas (la cita existe, el objetivo existe, no hay URLs). Un juez sin calibrar comparte los puntos ciegos del modelo.
- **Sin respaldo heurístico:** el informe dependería de que el modelo converja.

## Consecuencias
+ Siempre hay informe, con o sin modelo (`--no-llm`), y cada afirmación es verificable.
+ Los evals usan un grader 100 % de código.
− Los respaldos heurísticos son más pobres en redacción y vínculos (coincidencia de palabras).
! Una regla del crítico puede faltar. El 09/10, en uso real, el modelo devolvió un plan vacío con un ticket abierto y el crítico no tenía regla para eso. Esa vez el plan vacío era correcto: un bloque de 09 a 18 h no dejaba huecos. Igual faltaba la regla. Ahora se rechaza un plan vacío **si** hay tickets y huecos de al menos 60 min (`39-planner-plan-vacio`). Mitigación general: cada hueco que aparece en uso real se vuelve una regla y un caso del golden dataset.
