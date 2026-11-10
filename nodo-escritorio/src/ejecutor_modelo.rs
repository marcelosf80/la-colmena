//! Abstrae la ejecución del bloque de capas asignado. La implementación real
//! debe hacer binding FFI a `llama.cpp` (crate `llama-cpp-2` o equivalente)
//! para cargar el rango de capas en memoria y ejecutar el forward pass de
//! una activación recibida del nodo anterior en la cadena.
//!
//! Se deja detrás de un trait a propósito: así el resto del nodo (red,
//! políticas, control de usuario) se puede testear sin compilar ni enlazar
//! contra `llama.cpp`, que no está disponible en este entorno de desarrollo.

use anyhow::Result;

/// Activación intermedia que viaja entre nodos de una misma cadena.
/// Hoy es un placeholder de bytes; el formato real lo define
/// `packages/protocolo` (tensor serializado).
pub type Activacion = Vec<u8>;

pub trait MotorInferencia: Send + Sync {
    /// Carga en memoria el rango de capas [capa_desde, capa_hasta) del
    /// modelo ubicado en `ruta_pesos`.
    fn cargar(&mut self, ruta_pesos: &str, capa_desde: u32, capa_hasta: u32) -> Result<()>;

    /// Ejecuta el forward pass de las capas cargadas sobre `entrada` y
    /// devuelve la activación resultante para el siguiente nodo de la cadena.
    fn procesar(&self, entrada: &Activacion) -> Result<Activacion>;

    fn capas_cargadas(&self) -> Option<(u32, u32)>;
}

/// Implementación de desarrollo: no ejecuta inferencia real, solo valida el
/// contrato (carga/procesa) para poder testear el resto del nodo end-to-end
/// sin pesos reales. Reemplazar por `MotorLlamaCpp` cuando se integren los
/// bindings FFI.
#[derive(Default)]
pub struct MotorSimulado {
    rango_capas: Option<(u32, u32)>,
}

impl MotorInferencia for MotorSimulado {
    fn cargar(&mut self, _ruta_pesos: &str, capa_desde: u32, capa_hasta: u32) -> Result<()> {
        if capa_desde >= capa_hasta {
            anyhow::bail!("Rango de capas inválido: {capa_desde}..{capa_hasta}");
        }
        self.rango_capas = Some((capa_desde, capa_hasta));
        Ok(())
    }

    fn procesar(&self, entrada: &Activacion) -> Result<Activacion> {
        if self.rango_capas.is_none() {
            anyhow::bail!("No se puede procesar: ningún bloque de capas está cargado");
        }
        // Eco simulado — en la implementación real acá va el forward pass.
        Ok(entrada.clone())
    }

    fn capas_cargadas(&self) -> Option<(u32, u32)> {
        self.rango_capas
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_procesa_sin_cargar_capas_primero() {
        let motor = MotorSimulado::default();
        let resultado = motor.procesar(&vec![1, 2, 3]);
        assert!(resultado.is_err());
    }

    #[test]
    fn procesa_despues_de_cargar() {
        let mut motor = MotorSimulado::default();
        motor.cargar("modelo.gguf", 0, 8).unwrap();
        let resultado = motor.procesar(&vec![1, 2, 3]).unwrap();
        assert_eq!(resultado, vec![1, 2, 3]);
    }

    #[test]
    fn rechaza_rango_de_capas_invalido() {
        let mut motor = MotorSimulado::default();
        assert!(motor.cargar("modelo.gguf", 8, 8).is_err());
        assert!(motor.cargar("modelo.gguf", 10, 4).is_err());
    }

    #[test]
    fn reporta_el_rango_cargado() {
        let mut motor = MotorSimulado::default();
        motor.cargar("modelo.gguf", 8, 16).unwrap();
        assert_eq!(motor.capas_cargadas(), Some((8, 16)));
    }
}
