//! Benchmark mínimo de arranque: mide tokens/s con el motor ya cargado.
//!
//! Se ejecuta una sola vez, antes de registrarse en el coordinador, con un
//! `n_predict` chico (`--tokens-benchmark`, 16 por defecto). Así el nodo
//! reporta una velocidad real medida en esta máquina y no un valor fijo.
//!
//! Limitación conocida: es una medición puntual con un prompt corto, no un
//! benchmark estadístico. Sirve para que el planificador y las métricas
//! tengan una referencia honesta; no para comparar hardware con precisión.

use std::time::Instant;

use crate::ejecutor_modelo::MotorInferencia;

/// Prompt fijo: la medición busca velocidad de generación, no calidad.
pub const PROMPT_BENCHMARK: &str = "Responde solo: ok";

/// Calcula tokens por segundo. Aislada para poder testearla sin reloj.
pub fn tokens_por_segundo(tokens: u64, segundos: f64) -> f64 {
    if tokens == 0 || segundos <= 0.0 {
        return 0.0;
    }
    tokens as f64 / segundos
}

/// Corre el motor con un límite de tokens y devuelve tokens/s medidos.
/// Devuelve 0.0 si el motor falla o no reporta tokens (ej. simulado).
pub fn medir_tokens_por_segundo(motor: &dyn MotorInferencia, max_tokens: u32) -> f64 {
    let inicio = Instant::now();
    let entrada = PROMPT_BENCHMARK.as_bytes().to_vec();
    if motor
        .procesar_con_limite(&entrada, max_tokens)
        .is_err()
    {
        return 0.0;
    }
    let segundos = inicio.elapsed().as_secs_f64();
    tokens_por_segundo(motor.tokens_de_ultima_ejecucion(), segundos)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ejecutor_modelo::Activacion;
    use anyhow::Result;

    struct MotorDePrueba {
        tokens: u64,
        falla: bool,
    }

    impl MotorInferencia for MotorDePrueba {
        fn cargar(&mut self, _ruta: &str, _desde: u32, _hasta: u32) -> Result<()> {
            Ok(())
        }

        fn procesar(&self, entrada: &Activacion) -> Result<Activacion> {
            if self.falla {
                anyhow::bail!("motor roto");
            }
            Ok(entrada.clone())
        }

        fn tokens_de_ultima_ejecucion(&self) -> u64 {
            self.tokens
        }

        fn capas_cargadas(&self) -> Option<(u32, u32)> {
            Some((0, 8))
        }
    }

    #[test]
    fn tokens_por_segundo_evita_division_por_cero() {
        assert_eq!(tokens_por_segundo(0, 1.0), 0.0);
        assert_eq!(tokens_por_segundo(10, 0.0), 0.0);
        assert_eq!(tokens_por_segundo(10, -1.0), 0.0);
    }

    #[test]
    fn tokens_por_segundo_calcula_la_tasa() {
        assert_eq!(tokens_por_segundo(20, 2.0), 10.0);
        assert!((tokens_por_segundo(7, 0.5) - 14.0).abs() < f64::EPSILON);
    }

    #[test]
    fn benchmark_devuelve_cero_si_el_motor_falla() {
        let motor = MotorDePrueba {
            tokens: 100,
            falla: true,
        };
        assert_eq!(medir_tokens_por_segundo(&motor, 16), 0.0);
    }

    #[test]
    fn benchmark_devuelve_cero_si_el_motor_no_reporta_tokens() {
        let motor = MotorDePrueba {
            tokens: 0,
            falla: false,
        };
        assert_eq!(medir_tokens_por_segundo(&motor, 16), 0.0);
    }
}
