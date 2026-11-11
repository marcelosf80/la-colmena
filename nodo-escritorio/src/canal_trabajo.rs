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

use std::thread;
use std::time::Duration;

use serde::Deserialize;
use tokio::sync::mpsc::UnboundedSender;
use tungstenite::Message;
use tracing::{info, warn};

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

pub fn iniciar(url: String, emisor: UnboundedSender<Asignacion>) -> thread::JoinHandle<()> {
    thread::spawn(move || bucle_conexion(&url, emisor))
}

fn bucle_conexion(url: &str, emisor: UnboundedSender<Asignacion>) {
    loop {
        match tungstenite::connect(url) {
            Ok((mut socket, _respuesta)) => {
                info!(url, "canal de trabajo WebSocket conectado");
                loop {
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
}
