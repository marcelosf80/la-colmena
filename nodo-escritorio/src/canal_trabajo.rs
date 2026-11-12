//! Canal de trabajo: WebSocket saliente hacia el coordinador.
//!
//! El nodo siempre inicia la conexión (nunca expone puertos, igual que el
//! registro HTTP), así que funciona detrás de NAT doméstico sin configurar
//! nada. La conexión corre en un hilo bloqueante propio (`tungstenite` +
//! `std::net`) para no acoplar el runtime async al cliente WebSocket, en
//! línea con la decisión de usar `minreq` en vez de un stack HTTP async.
//!
//! El hilo reconecta con backoff ante cortes y entrega cada asignación por
//! un canal `tokio::sync::mpsc` al loop principal, que es quien decide si
//! acepta ejecutar (control de usuario + política de recursos).
//!
//! El canal es bidireccional: además de recibir asignaciones, el loop
//! principal puede empujar `MensajeResultado` de vuelta (vía un
//! `std::sync::mpsc::Sender`, no `tokio`, porque el hilo que escribe al
//! socket es bloqueante). Como `socket.read()` bloquearía indefinidamente y
//! nunca dejaría lugar para drenar la cola de salida, el socket se pone en
//! modo con timeout de lectura corto: cada vuelta del loop primero intenta
//! vaciar la cola de resultados pendientes y después intenta leer, tratando
//! un timeout de lectura como "nada nuevo todavía" en vez de un corte real.

use std::sync::mpsc::{Receiver, Sender};
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tokio::sync::mpsc::UnboundedSender;
use tracing::{info, warn};
use tungstenite::stream::MaybeTlsStream;
use tungstenite::Message;

/// Cuánto espera `socket.read()` antes de devolver el control para que el
/// loop pueda revisar si hay un resultado pendiente de enviar.
const TIMEOUT_LECTURA: Duration = Duration::from_millis(200);

/// Mensaje `asignacion` del coordinador (ver `app/api/websockets.py`).
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct Asignacion {
    #[serde(default)]
    pub tipo: String,
    #[serde(default)]
    pub trabajo_id: String,
    #[serde(default)]
    pub modelo_hash: String,
    #[serde(default)]
    pub posicion: u32,
    #[serde(default)]
    pub cadena: Vec<String>,
    #[serde(default)]
    pub siguiente_nodo_id: Option<String>,
    #[serde(default)]
    pub timeout_ms: u64,
}

/// Intervalo entre reintentos de conexión. Corto a propósito: la red de
/// nodos debe recuperarse rápido de un reinicio del coordinador.
const ESPERA_RECONEXION: Duration = Duration::from_secs(5);

/// Mensaje `resultado` hacia el coordinador (ver `app/api/websockets.py`).
/// Cierra el ciclo de una asignación: el nodo ya corrió el motor y devuelve
/// el texto generado (o el error, si falló).
#[derive(Debug, Clone, Serialize)]
pub struct MensajeResultado {
    pub tipo: String,
    pub trabajo_id: String,
    pub exito: bool,
    #[serde(default)]
    pub texto: String,
    #[serde(default)]
    pub error: String,
}

impl MensajeResultado {
    pub fn exitoso(trabajo_id: impl Into<String>, texto: impl Into<String>) -> Self {
        Self {
            tipo: "resultado".to_string(),
            trabajo_id: trabajo_id.into(),
            exito: true,
            texto: texto.into(),
            error: String::new(),
        }
    }

    pub fn fallido(trabajo_id: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            tipo: "resultado".to_string(),
            trabajo_id: trabajo_id.into(),
            exito: false,
            texto: String::new(),
            error: error.into(),
        }
    }
}

/// Arranca el hilo del canal. Devuelve el `JoinHandle` y un `Sender` para
/// que el loop principal empuje resultados de vuelta al coordinador por la
/// misma conexión.
pub fn iniciar(
    url: String,
    emisor_asignaciones: UnboundedSender<Asignacion>,
) -> (thread::JoinHandle<()>, Sender<MensajeResultado>) {
    let (emisor_resultados, receptor_resultados) = std::sync::mpsc::channel();
    let manija = thread::spawn(move || bucle_conexion(&url, emisor_asignaciones, receptor_resultados));
    (manija, emisor_resultados)
}

/// Pone un timeout de lectura corto en el stream TCP subyacente. Sin TLS
/// (conexiones `ws://` a la red local de nodos) el stream siempre es la
/// variante `Plain`; si en el futuro se agrega `wss://` esto deja de aplicar
/// el timeout y el comportamiento vuelve a ser el de lectura bloqueante —
/// peor, pero no roto.
fn aplicar_timeout_lectura(socket: &tungstenite::WebSocket<MaybeTlsStream<std::net::TcpStream>>) {
    if let MaybeTlsStream::Plain(tcp) = socket.get_ref() {
        if let Err(error) = tcp.set_read_timeout(Some(TIMEOUT_LECTURA)) {
            warn!(%error, "no se pudo fijar el timeout de lectura del canal");
        }
    }
}

fn es_timeout_de_lectura(error: &tungstenite::Error) -> bool {
    matches!(
        error,
        tungstenite::Error::Io(e)
            if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut
    )
}

fn bucle_conexion(
    url: &str,
    emisor: UnboundedSender<Asignacion>,
    receptor_resultados: Receiver<MensajeResultado>,
) {
    loop {
        match tungstenite::connect(url) {
            Ok((mut socket, _respuesta)) => {
                info!(url, "canal de trabajo WebSocket conectado");
                aplicar_timeout_lectura(&socket);

                'canal: loop {
                    // Vaciar resultados pendientes antes de bloquear en la
                    // lectura: así una respuesta del motor no espera hasta
                    // el próximo timeout de lectura para salir.
                    while let Ok(resultado) = receptor_resultados.try_recv() {
                        match serde_json::to_string(&resultado) {
                            Ok(json) => {
                                if let Err(error) = socket.send(Message::Text(json)) {
                                    warn!(%error, "no se pudo enviar el resultado, reconectando");
                                    break 'canal;
                                }
                            }
                            Err(error) => {
                                warn!(%error, "no se pudo serializar el resultado, se descarta");
                            }
                        }
                    }

                    match socket.read() {
                        Ok(Message::Text(texto)) => {
                            match serde_json::from_str::<Asignacion>(&texto) {
                                Ok(asignacion) if asignacion.tipo == "asignacion" => {
                                    if emisor.send(asignacion).is_err() {
                                        info!("el loop principal se cerró: fin del canal");
                                        return;
                                    }
                                }
                                Ok(otro) => {
                                    warn!(tipo = %otro.tipo, "mensaje del coordinador ignorado");
                                }
                                Err(error) => {
                                    warn!(%error, "mensaje del coordinador con formato inválido");
                                }
                            }
                        }
                        Ok(Message::Close(_)) => {
                            info!("el coordinador cerró el canal, reconectando");
                            break;
                        }
                        Ok(_) => {}
                        Err(error) if es_timeout_de_lectura(&error) => {
                            // Nada para leer todavía: vuelve al principio del
                            // loop a revisar la cola de salida.
                            continue;
                        }
                        Err(error) => {
                            warn!(%error, "canal WebSocket cortado, reconectando");
                            break;
                        }
                    }
                }
            }
            Err(error) => {
                warn!(%error, url, "no se pudo abrir el canal de trabajo");
            }
        }
        thread::sleep(ESPERA_RECONEXION);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parsea_una_asignacion_del_coordinador() {
        let json = r#"{
            "tipo": "asignacion",
            "trabajo_id": "abc-123",
            "modelo_hash": "hash-modelo",
            "posicion": 0,
            "cadena": ["n0", "n1"],
            "siguiente_nodo_id": "n1",
            "timeout_ms": 60000
        }"#;

        let asignacion: Asignacion = serde_json::from_str(json).unwrap();

        assert_eq!(asignacion.tipo, "asignacion");
        assert_eq!(asignacion.trabajo_id, "abc-123");
        assert_eq!(asignacion.cadena, vec!["n0".to_string(), "n1".to_string()]);
        assert_eq!(asignacion.siguiente_nodo_id.as_deref(), Some("n1"));
        assert_eq!(asignacion.timeout_ms, 60_000);
    }

    #[test]
    fn tolera_campos_opcionales_ausentes() {
        let asignacion: Asignacion =
            serde_json::from_str(r#"{"tipo": "asignacion", "trabajo_id": "t1"}"#).unwrap();

        assert!(asignacion.cadena.is_empty());
        assert_eq!(asignacion.siguiente_nodo_id, None);
        assert_eq!(asignacion.timeout_ms, 0);
    }

    #[test]
    fn ignora_mensajes_que_no_son_json_de_asignacion() {
        assert!(serde_json::from_str::<Asignacion>("no-es-json").is_err());
    }

    #[test]
    fn resultado_exitoso_serializa_con_los_campos_que_espera_el_coordinador() {
        // Contrato con `app/api/websockets.py::_procesar_resultado`: debe
        // traer tipo, trabajo_id, exito y texto.
        let mensaje = MensajeResultado::exitoso("t1", "hola mundo");
        let json = serde_json::to_value(&mensaje).unwrap();

        assert_eq!(json["tipo"], "resultado");
        assert_eq!(json["trabajo_id"], "t1");
        assert_eq!(json["exito"], true);
        assert_eq!(json["texto"], "hola mundo");
        assert_eq!(json["error"], "");
    }

    #[test]
    fn resultado_fallido_serializa_exito_false_con_el_error() {
        let mensaje = MensajeResultado::fallido("t2", "timeout del motor");
        let json = serde_json::to_value(&mensaje).unwrap();

        assert_eq!(json["exito"], false);
        assert_eq!(json["error"], "timeout del motor");
        assert_eq!(json["texto"], "");
    }

    #[test]
    fn es_timeout_de_lectura_reconoce_wouldblock_y_timedout() {
        let would_block =
            tungstenite::Error::Io(std::io::Error::from(std::io::ErrorKind::WouldBlock));
        let timed_out =
            tungstenite::Error::Io(std::io::Error::from(std::io::ErrorKind::TimedOut));
        let otro = tungstenite::Error::ConnectionClosed;

        assert!(es_timeout_de_lectura(&would_block));
        assert!(es_timeout_de_lectura(&timed_out));
        assert!(!es_timeout_de_lectura(&otro));
    }
}
