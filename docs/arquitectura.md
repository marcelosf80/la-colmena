# Arquitectura

## Componentes

- **Coordinador** (Python 3.11+ / FastAPI): registra nodos, arma cadenas de
  cómputo para cada consulta, lleva el libro mayor de créditos. No ejecuta
  inferencia.
- **Nodo de escritorio** (Rust o Go, pendiente): daemon que el usuario
  instala, ejecuta un bloque de capas del modelo vía `llama.cpp` y reporta
  su estado al coordinador.
- **Nodo Android** (Kotlin, pendiente): mismo rol que el nodo de escritorio,
  como servicio en primer plano con restricciones de batería/red.
- **Protocolo** (`packages/protocolo/`): esquema Protobuf compartido por
  todas las implementaciones.

## Modelo de dominio del coordinador

- `Nodo`: identidad, recursos donados, estado (conectado, ocupado, caído).
- `PosicionModelo`: un bloque de capas de un modelo (`modelo_hash`,
  `posicion`, rango de capas).
- `Candidato`: relación nodo↔posición, con su carga actual
  (`consultas_en_curso`).
- `Trabajo`: una consulta de un usuario, con su cadena de nodos asignada.
- `Planificador`: función pura que, dada una lista de candidatos por
  posición, arma la cadena eligiendo el menos cargado en cada una.
- `LibroCreditos`: registra aportes y consumos, calcula el ratio de cada
  cuenta.

## Decisiones de diseño activas

1. Throughput escala con la cantidad de nodos; la latencia de una consulta
   individual no mejora agregando nodos a una misma cadena.
2. Varias réplicas por posición evitan que un solo nodo sea cuello de
   botella.
3. El coordinador es el único punto central deliberado del MVP — ver
   `docs/decisiones-abiertas.md` (pendiente) para la discusión sobre
   descentralización futura.

Gaps de seguridad, latencia acotada y condiciones de carrera documentados
en el informe de auditoría entregado antes de este scaffold siguen
pendientes de implementación.
