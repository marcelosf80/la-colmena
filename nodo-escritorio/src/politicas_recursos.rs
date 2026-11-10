//! Límites de recursos que el usuario dona. Todo acá son funciones puras
//! sobre datos ya medidos — la medición real (sysinfo) vive en main.rs, para
//! poder testear la política sin depender del sistema operativo.
//!
//! `capas_que_entran` aún no tiene llamador: se conecta cuando el nodo lea
//! el tamaño por capa desde el catálogo de modelos (Fase 1).
#![allow(dead_code)]

#[derive(Debug, Clone, Copy)]
pub struct PoliticaRecursos {
    pub ram_max_mb: u64,
    pub cpu_max_pct: f32,
}

impl PoliticaRecursos {
    pub fn new(ram_max_mb: u64, cpu_max_pct: f32) -> Self {
        Self {
            ram_max_mb,
            cpu_max_pct,
        }
    }

    /// Si el uso actual del sistema ya supera lo que el usuario donó, el
    /// nodo debe dejar de aceptar trabajo nuevo hasta que baje.
    pub fn dentro_de_limite(&self, uso_ram_mb: u64, uso_cpu_pct: f32) -> bool {
        uso_ram_mb <= self.ram_max_mb && uso_cpu_pct <= self.cpu_max_pct
    }
}

/// Cuántas capas de un modelo entran en la RAM donada, dado el peso
/// aproximado de cada capa. Resultado conservador: redondea hacia abajo.
pub fn capas_que_entran(ram_donada_mb: u64, mb_por_capa: u64) -> u32 {
    if mb_por_capa == 0 {
        return 0;
    }
    (ram_donada_mb / mb_por_capa) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dentro_de_limite_cuando_uso_es_menor() {
        let politica = PoliticaRecursos::new(4096, 50.0);
        assert!(politica.dentro_de_limite(2048, 30.0));
    }

    #[test]
    fn fuera_de_limite_cuando_ram_excede() {
        let politica = PoliticaRecursos::new(4096, 50.0);
        assert!(!politica.dentro_de_limite(5000, 10.0));
    }

    #[test]
    fn fuera_de_limite_cuando_cpu_excede() {
        let politica = PoliticaRecursos::new(4096, 50.0);
        assert!(!politica.dentro_de_limite(100, 80.0));
    }

    #[test]
    fn en_el_limite_exacto_se_considera_dentro() {
        let politica = PoliticaRecursos::new(4096, 50.0);
        assert!(politica.dentro_de_limite(4096, 50.0));
    }

    #[test]
    fn capas_que_entran_redondea_hacia_abajo() {
        assert_eq!(capas_que_entran(1000, 300), 3);
    }

    #[test]
    fn capas_que_entran_es_cero_sin_ram() {
        assert_eq!(capas_que_entran(0, 300), 0);
    }

    #[test]
    fn capas_que_entran_es_cero_si_mb_por_capa_es_cero() {
        assert_eq!(capas_que_entran(1000, 0), 0);
    }
}
