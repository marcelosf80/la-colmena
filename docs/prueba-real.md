# Prueba real con 2 (o más) PCs

Esta guía es para el último ítem pendiente de la hoja de ruta: todo lo que
hay hasta ahora está probado con tests y `TestClient`, nunca corrió en
hardware real con más de una máquina. Acá se arma esa prueba.

## Qué vas a necesitar

1. **Dos PCs en la misma red** (o la misma PC dos veces, para una primera
   prueba antes de mover cables — ver "Prueba en una sola PC" más abajo).
2. **`llama-server`**, el binario oficial de
   [llama.cpp](https://github.com/ggml-org/llama.cpp/releases) — buscá el
   release más reciente y bajá el paquete que corresponda a tu sistema
   (Windows: `llama-*-bin-win-*.zip`; Linux: `llama-*-bin-ubuntu-*.zip`).
   Descomprimilo en una carpeta cualquiera, por ejemplo `C:\colmena\` o
   `~/colmena/`. El ejecutable que importa es `llama-server.exe` (Windows)
   o `llama-server` (Linux).
3. **Un modelo chico en formato `.gguf`**, para que la primera prueba sea
   rápida y liviana. Recomendado: un modelo de 1B a 3B parámetros,
   cuantizado a 4 bits (`Q4_K_M`), de [Hugging
   Face](https://huggingface.co/models?library=gguf&sort=trending) —
   buscá `gguf` en el nombre. Un modelo así pesa unos cientos de MB.
4. **Rust** (`cargo`) en cada PC que vaya a correr un nodo:
   [rustup.rs](https://rustup.rs).
5. **Python 3.11+** en la PC que corra el coordinador.

No hace falta instalar nada más: los scripts de `scripts/` se encargan del
entorno virtual de Python y de compilar el nodo.

## Paso 1 — Elegir qué PC es el coordinador

Una sola PC corre el coordinador (el "servidor" de la red). Puede ser
cualquiera de las dos, y **también puede correr un nodo al mismo tiempo**
— coordinador y nodo son procesos independientes.

En esa PC, desde la raíz del repo:

**Windows (PowerShell):**
```powershell
.\scripts\iniciar-coordinador.ps1
```

**Linux/Mac:**
```bash
./scripts/iniciar-coordinador.sh
```

El script te va a mostrar algo así:

```
Desde ESTA PC:              http://localhost:8000
Desde OTRAS PCs de tu red:   http://192.168.1.10:8000
```

**Anotá esa segunda URL** — es la que vas a usar en el `-Coordinador`/
`COORDINADOR` de los nodos de las *otras* PCs.

### Si Windows bloquea la conexión

La primera vez que corras el coordinador, Windows puede preguntar si
permitís que Python acceda a la red. Elegí **"Permitir acceso"** y marcá
al menos **"Redes privadas"**. Si ya le dijiste que no por error: Panel de
control → Firewall de Windows Defender → "Permitir una aplicación a
través del Firewall" → buscá Python y habilitá "Privada".

## Paso 2 — Correr un nodo en cada PC

En **cada** PC que done cómputo (incluida la del coordinador, si querés
que también aporte), desde la raíz del repo:

**Windows:**
```powershell
.\scripts\iniciar-nodo.ps1 `
    -Coordinador "http://192.168.1.10:8000" `
    -ModeloHash "prueba-1" `
    -LlamaServer "C:\colmena\llama-server.exe" `
    -Pesos "C:\colmena\modelos\tu-modelo.gguf"
```

**Linux/Mac:**
```bash
MODELO_HASH=prueba-1 \
COORDINADOR=http://192.168.1.10:8000 \
LLAMA_SERVER=~/colmena/llama-server \
PESOS=~/colmena/modelos/tu-modelo.gguf \
./scripts/iniciar-nodo.sh
```

**`-ModeloHash`/`MODELO_HASH` tiene que ser EXACTAMENTE el mismo string en
las dos PCs** (y en la consulta que mandes después) — es como el
coordinador sabe que esos nodos pueden atender la misma consulta. No hace
falta que sea un hash de verdad, cualquier string sirve (`"prueba-1"`,
`"llama3-8b"`, lo que quieras) mientras sea igual en todos lados.

La primera vez, `cargo build --release` tarda unos minutos. Las siguientes
veces es casi instantáneo (solo recompila si cambió el código).

Vas a ver en el log del nodo algo como:

```
registrado en el coordinador
canal de trabajo WebSocket conectado
heartbeat enviado al coordinador
```

Si en vez de eso ves un error de conexión, revisá que la URL del
coordinador sea la correcta (la IP, no `localhost`, si es otra PC) y que
el firewall no esté bloqueando.

## Paso 3 — Mandar una consulta

Desde cualquier PC (no hace falta que sea ninguna de las dos anteriores),
con `curl` o el navegador para el `GET`:

```bash
curl -X POST http://192.168.1.10:8000/consultas \
  -H "Content-Type: application/json" \
  -d '{
    "usuario_id": "marcelo",
    "modelo_hash": "prueba-1",
    "total_posiciones": 1,
    "prompt": "Contame un chiste corto"
  }'
```

Te devuelve un `trabajo_id`. Con eso, consultá el resultado:

```bash
curl http://192.168.1.10:8000/consultas/<trabajo_id>
```

Al principio va a decir `"estado": "en_curso"`. Esperá unos segundos
(depende de qué tan rápido sea el modelo en esa PC) y volvé a consultar —
debería decir `"estado": "completado"` con el texto generado en
`texto_resultado`.

**Mirá el log del nodo que atendió la consulta**: vas a ver la asignación
llegando, el motor procesándola, y el resultado volviendo al coordinador.
Si tenés dos nodos con el mismo `modelo_hash`, mandá varias consultas
seguidas y vas a ver que el coordinador reparte entre los dos (el
planificador elige el menos cargado).

## Paso 4 — Probar verificación por réplicas (opcional)

Con al menos dos nodos registrados para el mismo `modelo_hash`, podés
activar la verificación por réplicas (manda cada consulta a dos nodos
independientes y compara). Reiniciá el coordinador con la variable de
entorno:

**Windows:**
```powershell
$env:COMUNIDAD_IA_TASA_VERIFICACION = "1.0"
.\scripts\iniciar-coordinador.ps1
```

**Linux/Mac:**
```bash
COMUNIDAD_IA_TASA_VERIFICACION=1.0 ./scripts/iniciar-coordinador.sh
```

Mandá una consulta igual que en el Paso 3. La respuesta va a incluir
`"verificacion_activa": true`, y vas a ver en los logs de LOS DOS nodos
que recibieron la misma consulta. Con `GET /consultas/<trabajo_id>`
vas a ver `cadena_verificacion`, `resultado_primario` y
`resultado_secundario`.

**Ojo con esto**: si tu modelo tiene temperatura > 0 (el valor por
defecto de `llama-server` no es 0), es esperable que a veces la
verificación falle por discrepancia aunque los dos nodos funcionen bien
— es la limitación conocida, documentada en
[`heartbeat-y-canal.md`](heartbeat-y-canal.md#verificación-por-réplicas).
Para que coincidan de forma confiable, lanzá `llama-server` con `--temp 0`
en los dos nodos (pasale ese flag manualmente si corrés el binario sin el
script, o esperá a que se agregue como opción del nodo — está en la hoja
de ruta).

## Prueba en una sola PC (antes de usar dos máquinas)

Para validar que todo funciona antes de meter una segunda PC en la
ecuación, podés correr coordinador + dos nodos en la misma máquina, cada
uno en su propia terminal:

- Terminal 1: `./scripts/iniciar-coordinador.sh` (o el `.ps1`)
- Terminal 2: nodo con `--nodo-id nodo-a`
- Terminal 3: nodo con `--nodo-id nodo-b` (mismo `--modelo-hash` que el A)
- Terminal 4: los `curl` del Paso 3, contra `http://localhost:8000`

Si esto funciona, el salto a dos PCs es solo cambiar `localhost` por la IP
real en el Paso 2.

## Qué anotar de esta prueba

Si corrés esto, vale la pena registrar en `docs/bitacora.md`:

- Qué modelo y qué tamaño de cuantización usaste.
- Cuánto tardó una consulta de punta a punta (latencia real, no la de
  `/metricas` que mide desde el despacho, sino desde que mandaste el
  `curl`).
- Si usaste verificación: ¿coincidieron las respuestas con temperatura
  por defecto, o hubo que bajarla a 0?
- Cualquier error que no esté ya documentado acá.
