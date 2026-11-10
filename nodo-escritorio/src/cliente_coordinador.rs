//! Cliente del coordinador. El nodo siempre inicia la conexión hacia afuera
//! (nunca expone un puerto entrante), así se evita lidiar con NAT en redes
//! domésticas.
//!
//! Se usa `minreq` en vez de un cliente más pesado (reqwest/hyper) a
//! propósito: es bloqueante y de pocas dependencias, lo que simplifica el
//! binario final que el usuario instala. Las llamadas se delegan a
//! `tokio::task::spawn_blocking` para no bloquear el runtime async.

use anyhow::{bail, Context, Result};
use serde::Serialize;

#[derive(Debug, Serialize, Clone)]
pub struct RegistroNodo {
    pub nodo_id: String,
    pub ram_donada_mb: u64,
    pub cores_donados: u32,
    pub tiene_gpu: bool,
    pub modelo_hash: String,
    pub posicion: u32,
    pub tokens_por_segundo: f64,
}

#[derive(Clone)]
pub struct ClienteCoordinador {
    base_url: String,
}

impl ClienteCoordinador {
    pub fn nuevo(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
        }
    }

    pub async fn registrar(&self, registro: &RegistroNodo) -> Result<()> {
        let url = format!("{}/nodos/registro", self.base_url);
        let registro = registro.clone();

        tokio::task::spawn_blocking(move || -> Result<()> {
            let cuerpo = serde_json::to_vec(&registro)?;
            let respuesta = minreq::post(&url)
                .with_header("Content-Type", "application/json")
                .with_body(cuerpo)
                .send()
                .context("fallo de red al registrar el nodo")?;

            if !(200..300).contains(&respuesta.status_code) {
                bail!(
                    "el coordinador rechazó el registro: status {}",
                    respuesta.status_code
                );
            }
            Ok(())
        })
        .await
        .context("la tarea de registro falló al ejecutarse")??;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registro_nodo_serializa_con_los_nombres_de_campo_del_coordinador() {
        // Garantiza que el contrato con la API Python (snake_case, mismos
        // nombres) no se rompe silenciosamente si alguien renombra un campo.
        let registro = RegistroNodo {
            nodo_id: "n1".into(),
            ram_donada_mb: 4096,
            cores_donados: 4,
            tiene_gpu: false,
            modelo_hash: "hash".into(),
            posicion: 0,
            tokens_por_segundo: 5.0,
        };
        let json = serde_json::to_value(&registro).unwrap();
        for campo in [
            "nodo_id",
            "ram_donada_mb",
            "cores_donados",
            "tiene_gpu",
            "modelo_hash",
            "posicion",
            "tokens_por_segundo",
        ] {
            assert!(json.get(campo).is_some(), "falta el campo {campo}");
        }
    }
}
