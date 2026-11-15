# Arquitectura

## Alcance del MVP: réplicas de modelos completos (Ruta A)

Cada nodo descarga y ejecuta el **modelo completo** con `llama-server`. El
coordinador reparte consultas entre los nodos disponibles y, opcionalmente,
despacha una segunda copia a una cadena independiente para verificar el
resultado.

```text
Usuario -> Coordinador -> [Nodo A: modelo completo] -> resultado
                       -> [Nodo B: modelo completo]  (réplica / verificación)
```

- La red **suma capacidad**, no memoria: un modelo que no cabe en una máquina
  no se puede servir entre varias con esta arquitectura.
- La **latencia** de una consulta no mejora agregando nodos: lo que crece es el
  throughput total y la tolerancia a fallos.
- `posicion` es un **slot lógico** para elegir réplicas del mismo modelo. No
  representa un rango de capas.

### Línea de I+D separada (Ruta B)

La inferencia particionada por capas (cada nodo ejecuta un segmento real del
modelo y transmite tensores/activaciones) es un producto técnicamente distinto:
requiere un runtime que soporte tensor/model parallel, pesos particionados,
transporte de tensores, manejo de KV cache y benchmarks de red. **No está
implementada** y no debe presentarse como una capacidad actual. Ver
`docs/bitacora.md` para la decisión registrada.

## Componentes

- **Coordinador** (Python 3.11+ / FastAPI): registra nodos, planifica el
  despacho, lleva el ciclo de vida de los trabajos y el libro mayor de
  créditos. No ejecuta inferencia.
- **Nodo de escritorio** (Rust): daemon que el usuario instala; ejecuta el
  modelo completo vía `llama-server` y reporta estado y resultados al
  coordinador.
- **Nodo Android** (Kotlin, fuera del MVP): mismo rol que el nodo de
  escritorio, como servicio en primer plano con restricciones de batería/red.
- **Protocolo** (`packages/protocolo/`): esquema Protobuf compartido por las
  implementaciones; todavía no está cableado al transporte (hoy JSON).

## Modelo de dominio del coordinador

- `Nodo`: identidad, recursos donados, estado (conectado, ocupado, caído).
- `PosicionModelo`: slot lógico de un modelo (`modelo_hash`, `posicion`). Sirve
  para agrupar réplicas; no describe capas.
- `Candidato`: relación nodo↔posición, con su carga actual
  (`consultas_en_curso`).
- `Trabajo`: una consulta de un usuario y la cadena lógica de nodos asignada.
  Estados: `EN_COLA`, `EN_CURSO`, `VERIFICANDO`, `COMPLETADO`, `FALLIDO`.
  Los terminales son inmutables ante resultados tardíos.
- `Planificador`: función pura que, dada una lista de candidatos por posición,
  arma la cadena eligiendo el menos cargado en cada una.
- `LibroCreditos`: registra aportes y consumos, calcula el ratio de cada
  cuenta. Todavía no está conectado a la verificación por réplicas.

## Decisiones de diseño activas

1. La capacidad escala con la cantidad de nodos; la latencia individual no
   mejora agregando nodos a la misma consulta.
2. Varias réplicas por posición evitan que un solo nodo sea cuello de botella.
3. El nodo inicia todas las conexiones (HTTP y WebSocket): funciona detrás de
   NAT doméstico sin abrir puertos.
4. La verificación por réplicas compara **texto exacto** y está apagada por
   defecto (`COMUNIDAD_IA_TASA_VERIFICACION=0.0`). Con sampling no
   determinístico, dos nodos honestos pueden diferir; falta temperatura 0 o una
   comparación tolerante.
5. El coordinador es el único punto central deliberado del MVP. La
   descentralización es una discusión futura, no una capacidad actual.

## Deuda conocida

Seguridad de producción (identidad criptográfica de nodos, TLS/WSS, límites de
tamaño/frecuencia, aislamiento del proceso `llama-server`), métricas reales de
hardware y una economía de créditos auditable siguen pendientes. Ver
`docs/bitacora.md` y el informe técnico del 15/11/2026.
