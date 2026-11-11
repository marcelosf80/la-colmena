//! Motor de inferencia real vía `llama-server` (binario oficial de
//! llama.cpp) como proceso hijo.
//!
//! Elección de diseño: en vez de un binding FFI (que exige compilar
//! llama.cpp con CMake + toolchain C++ en cada plataforma), el nodo usa el
//! binario precompilado oficial como servidor local en 127.0.0.1. Ventajas:
//! cero toolchain C++ para el usuario, aislamiento de memoria, y el
//! protocolo HTTP del servidor es estable. El nodo es quien baja el binario
//! y los pesos del catálogo (los pesos nunca viajan entre pares).
//!
//! Implementa el mismo trait `MotorInferencia`, así el resto del nodo
//! (despacho, políticas, control de usuario) no sabe qué motor corre.

use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use anyhow::{bail, Context, Result};
use serde::Deserialize;

use crate::ejecutor_modelo::{Activacion, MotorInferencia};

/// Reintentos para el healthcheck del servidor al arrancar (60 × 250 ms = 15 s).
const REINTENTOS_SALUD: u32 = 60;

const PAUSA_ENTRE_REINTENTOS: u64 = 250;
const TIMEOUT_REQUEST_MS: u64 = 1_500;

const TOKENS_PREDICHO_POR_DEFECTO: u32 = 256;

pub struct MotorServidorLlama {
    proceso: Option<Child>,
    url: String,
    rango_capas: Option<(u32, u32)>,
    ultimo_tokens: AtomicU64,
}

#[derive(Debug, Deserialize)]
struct RespuestaCompletion {
    #[serde(default)]
    content: Option<String>,
    #[serde(default)]
    tokens_predicted: Option<u64>,
}

impl MotorServidorLlama {
    /// Levanta `llama-server` con los pesos indicados y espera el healthcheck.
    pub fn iniciar(
        ruta_binario: &str,
        ruta_pesos: &str,
        puerto: u16,
    ) -> Result<Self> {
        let mut proceso = Command::new(ruta_binario)
            .arg("--model")
            .arg(ruta_pesos)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(puerto.to_string())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .with_context(|| format!("no se pudo iniciar el motor en {ruta_binario}"))?;

        let url = format!("http://127.0.0.1:{puerto}");
        match esperar_salud(&url) {
            Ok(()) => Ok(Self {
                proceso: Some(proceso),
                url,
                rango_capas: None,
                ultimo_tokens: AtomicU64::new(0),
            }),
            Err(error) => {
                let _ = proceso.kill();
                Err(error.context(
                    "llama-server no respondió a /health: revisá la ruta del binario y del .gguf",
                ))
            }
        }
    }

    /// Constructor para tests: toma un proceso ya creado (puede ser un
    /// dummy) y una URL que apunta a un servidor HTTP de mock.
    #[cfg(test)]
    pub fn desde_proceso(proceso: Child, url: String) -> Self {
        Self {
            proceso: Some(proceso),
            url,
            rango_capas: None,
            ultimo_tokens: AtomicU64::new(0),
        }
    }

    /// POST /completion del API de llama-server (no streaming).
    pub fn consultar(&self, prompt: &str) -> Result<String> {
        let url = format!("{}/completion", self.url);
        let cuerpo = serde_json::json!({
            "prompt": prompt,
            "n_predict": TOKENS_PREDICHO_POR_DEFECTO,
            "stream": false,
        });

        let respuesta = minreq::post(&url)
            .with_timeout(TIMEOUT_REQUEST_MS)
            .with_json(&cuerpo)
            .context("fallo de red al consultar el motor")?
            .send()
            .context("fallo de red al consultar el motor")?;

        if !(200..300).contains(&respuesta.status_code) {
            bail!("el motor rechazó la consulta: status {}", respuesta.status_code);
        }

        let completion: RespuestaCompletion =
            respuesta.json().context("respuesta del motor no es JSON válido")?;

        self.ultimo_tokens.store(
            completion.tokens_predicted.unwrap_or(0),
            Ordering::Relaxed,
        );

        Ok(completion.content.unwrap_or_default())
    }

    pub fn puerto(&self) -> Option<u16> {
        self.url
            .rsplit(':')
            .next()
            .and_then(|p| p.parse().ok())
    }
}

fn esperar_salud(url: &str) -> Result<()> {
    esperar_salud_con(url, REINTENTOS_SALUD, PAUSA_ENTRE_REINTENTOS, TIMEOUT_REQUEST_MS)
}

/// Parametrizada para poder testearla rápido sin colgarse 15 s.
fn esperar_salud_con(
    url: &str,
    reintentos: u32,
    pausa_ms: u64,
    timeout_ms: u64,
) -> Result<()> {
    let url_salud = format!("{url}/health");
    for _ in 0..reintentos {
        if let Ok(respuesta) =
            minreq::get(&url_salud).with_timeout(timeout_ms).send()
        {
            if (200..300).contains(&respuesta.status_code) {
                return Ok(());
            }
        }
        std::thread::sleep(Duration::from_millis(pausa_ms));
    }
    bail!(
        "el motor no respondió /health en {url_salud} tras {reintentos} reintentos"
    );
}

impl Drop for MotorServidorLlama {
    fn drop(&mut self) {
        if let Some(ref mut proceso) = self.proceso.take() {
            let _ = proceso.kill();
            let _ = proceso.wait();
        }
    }
}

impl MotorInferencia for MotorServidorLlama {
    /// El servidor gestiona los pesos por sí solo: "cargar" es arrancarlo
    /// (ya hecho en `iniciar`). Este método valida el rango y queda
    /// como registro del bloque de capas que este nodo sirve.
    fn cargar(&mut self, _ruta_pesos: &str, capa_desde: u32, capa_hasta: u32) -> Result<()> {
        if capa_desde >= capa_hasta {
            bail!("Rango de capas inválido: {capa_desde}..{capa_hasta}");
        }
        self.rango_capas = Some((capa_desde, capa_hasta));
        Ok(())
    }

    /// La entrada es el prompt en UTF-8 (placeholder hasta que las
    /// activaciones reales viajen por el canal); la salida es el texto
    /// generado por el modelo.
    fn procesar(&self, entrada: &Activacion) -> Result<Activacion> {
        let prompt = String::from_utf8(entrada.clone())
            .context("la entrada del motor no es UTF-8 válido")?;
        let texto = self.consultar(&prompt)?;
        Ok(texto.into_bytes())
    }

    fn tokens_de_ultima_ejecucion(&self) -> u64 {
        self.ultimo_tokens.load(Ordering::Relaxed)
    }

    fn capas_cargadas(&self) -> Option<(u32, u32)> {
        self.rango_capas
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    /// Mock mínimo de llama-server: escucha en 127.0.0.1:0 y responde las
    /// rutas pedidas con HTTP plano. Nos permite probar el motor end-to-end
    /// (HTTP real incluido) sin necesidad del binario.
    fn arrancar_mock(rutas: Vec<String>) -> (u16, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let puerto = listener.local_addr().unwrap().port();
        let hilo = std::thread::spawn(move || {
            for ruta in rutas {
                let (mut stream, _) = listener.accept().unwrap();
                let mut buffer = [0u8; 8192];
                let _ = stream.read(&mut buffer);
                let peticion = String::from_utf8_lossy(&buffer);
                assert!(
                    peticion.contains(ruta.as_str()),
                    "el motor consultó {ruta} pero el mock no la sirve"
                );

                let cuerpo = if ruta.ends_with("health") {
                    String::new()
                } else {
                    r#"{"content":"hola del modelo","tokens_predicted":7}"#.to_string()
                };
                let respuesta = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    cuerpo.len(),
                    cuerpo
                );
                stream.write_all(respuesta.as_bytes()).unwrap();
                // Connection: close: cortamos para que minreq termine la lectura.
            }
        });
        (puerto, hilo)
    }

    fn proceso_dummy() -> Child {
        // Un proceso que no muere durante el test y se puede matar al dropear.
        if cfg!(windows) {
            Command::new("cmd")
                .args(["/c", "ping", "-n", "60", "127.0.0.1"])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap()
        } else {
            Command::new("sleep")
                .arg("60")
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap()
        }
    }

    #[test]
    fn health_ok_y_completado_del_mundo_real() {
        let (puerto, hilo_mock) = arrancar_mock(vec!["/completion".to_string()]);
        let motor = MotorServidorLlama::desde_proceso(
            proceso_dummy(),
            format!("http://127.0.0.1:{puerto}"),
        );

        let salida = motor.procesar(&b"saludo de prueba".to_vec()).unwrap();
        let texto = String::from_utf8(salida).unwrap();

        assert_eq!(texto, "hola del modelo");
        assert_eq!(motor.tokens_de_ultima_ejecucion(), 7);

        hilo_mock.join().unwrap();
    }

    #[test]
    fn esperar_salud_acepta_un_servidor_sano() {
        let (puerto, hilo_mock) = arrancar_mock(vec!["/health".to_string()]);
        let url = format!("http://127.0.0.1:{puerto}");

        assert!(esperar_salud(&url).is_ok());

        hilo_mock.join().unwrap();
    }

    #[test]
    fn esperar_salud_falla_si_nadie_responde() {
        // Parámetros chicos: el test no debe tardar nada. Un puerto cerrado
        // (o un servidor colgado) agota reintentos y devuelve error.
        let url = "http://127.0.0.1:1";
        assert!(esperar_salud_con(url, 3, 10, 200).is_err());
    }

    #[test]
    fn cargar_registra_el_rango_y_valida() {
        let motor = MotorServidorLlama::desde_proceso(
            proceso_dummy(),
            "http://127.0.0.1:1".into(),
        );
        // Necesita mut: testeamos vía un motor local.
        let mut motor = motor;
        motor.cargar("pesos.gguf", 8, 16).unwrap();
        assert_eq!(motor.capas_cargadas(), Some((8, 16)));
        assert!(motor.cargar("pesos.gguf", 16, 8).is_err());
    }

    #[test]
    fn entrada_no_utf8_falla_sin_llamar_al_servidor() {
        let motor = MotorServidorLlama::desde_proceso(
            proceso_dummy(),
            "http://127.0.0.1:1".into(), // puerto cerrado: no debe tocarse
        );
        assert!(motor.procesar(&vec![0xFF, 0xFE, 0x00]).is_err());
    }
}
