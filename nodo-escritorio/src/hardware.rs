//! Detección de hardware para reportar capacidad real al coordinador.
//!
//! Hoy solo se detecta NVIDIA vía `nvidia-smi`. AMD/Intel (ROCm, Vulkan,
//! Metal) quedan pendientes: si el usuario sabe que su GPU sirve para
//! `llama-server`, puede forzarlo con `--tiene-gpu true`.
//!
//! La detección es una consulta al driver, no una declaración del usuario:
//! si `nvidia-smi` no está o falla, se reporta sin GPU.

use std::process::Command;

/// `true` si la salida de `nvidia-smi --query-gpu=name` tiene al menos un
/// dispositivo. Aislada para poder testear el parseo sin driver real.
fn hay_gpu_en_salida(salida: &str) -> bool {
    !salida.trim().is_empty()
}

/// Detecta al menos una GPU NVIDIA disponible para el driver.
pub fn detectar_gpu() -> bool {
    match Command::new("nvidia-smi")
        .args(["--query-gpu=name", "--format=csv,noheader"])
        .output()
    {
        Ok(salida) if salida.status.success() => {
            hay_gpu_en_salida(&String::from_utf8_lossy(&salida.stdout))
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn salida_vacia_no_es_gpu() {
        assert!(!hay_gpu_en_salida(""));
        assert!(!hay_gpu_en_salida("   \n\t "));
    }

    #[test]
    fn nombre_de_dispositivo_es_gpu() {
        assert!(hay_gpu_en_salida("NVIDIA GeForce RTX 3060\n"));
        assert!(hay_gpu_en_salida("Tesla T4"));
    }
}
