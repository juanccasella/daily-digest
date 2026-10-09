# ADR-0001: Usamos LangGraph como orquestador
**Fecha:** 2026-10-09 · **Estado:** propuesta · **Quiénes:** Juan Cruz Casella (con Claude Code)

## Contexto
El digest junta seis fuentes (Jira abiertos, cambios de Jira, calendario, mails, chats, objetivos) y tres agentes LLM con un crítico en código. Necesitamos lecturas en paralelo, que una fuente caída no tumbe la corrida, un ciclo propuesta → crítica → feedback explícito y una traza por nodo.

## Decisión
Usamos LangGraph (`StateGraph`): fan-out de seis nodos de lectura desde `START`, join en `facts` y luego dos ramas (lector → vinculador, y planificador) que se unen en `render`. Las dependencias (fuentes, modelo, tracer) se inyectan por `config["configurable"]`, y así los evals cambian fuentes y modelo sin tocar el grafo.

## Alternativas consideradas
- **Python plano con `concurrent.futures`:** sin dependencias, pero el paralelismo, el estado compartido y los reducers (avisos de ramas paralelas) quedan a mano y son menos legibles para revisar.
- **Un solo agente con tools (ReAct):** menos código, pero mezcla datos no confiables con herramientas en el mismo contexto (ver ADR-0003) y deja la crítica en manos del modelo.
- **SDK de agentes / supervisor LLM:** más flexible, pero acá el ruteo es fijo y no necesita un LLM que decida el orden; agregaría costo y una superficie de fallo.

## Consecuencias
+ Paralelismo y joins declarativos; el diagrama del grafo es la documentación.
+ Evals deterministas: se inyectan `StaticSources` y `FakeLLM`.
− Dependencia de LangGraph y de su semántica de reducers (`Annotated[list, operator.add]` para los avisos).
! El ciclo de reintento vive dentro de cada agente (`run_agent`) y no como arista del grafo: es más simple, pero en el diagrama no se ve. Mitigación: queda en la traza (`digest.attempts`) y en el docstring de `graph.py`.
