//! Registro local, append-only, de los trabajos procesados por este nodo.
//! Sirve como respaldo verificable del lado del usuario frente a lo que el
//! coordinador le acredite en su cuenta de créditos.
//!
//! Pendiente de conectar en `main.rs`: hoy no hay loop de trabajo real
//! (Fase 1 agrega WebSocket + ejecución), así que estas funciones todavía no
//! tienen un llamador. Se mantienen con tests propios para no perder la
//! lógica ya validada cuando se conecten.
#![allow(dead_code)]

use anyhow::{Context, Result};
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Recibo {
    pub trabajo_id: String,
    pub tokens_procesados: u64,
}

/// Formato de línea: "trabajo_id,tokens_procesados". Separado en funciones
/// puras para poder testear el parseo sin tocar el sistema de archivos.
pub fn formatear(recibo: &Recibo) -> String {
    format!("{},{}", recibo.trabajo_id, recibo.tokens_procesados)
}

pub fn parsear(linea: &str) -> Option<Recibo> {
    let (trabajo_id, tokens) = linea.split_once(',')?;
    let tokens_procesados = tokens.trim().parse().ok()?;
    Some(Recibo {
        trabajo_id: trabajo_id.to_string(),
        tokens_procesados,
    })
}

pub fn registrar(ruta: &Path, recibo: &Recibo) -> Result<()> {
    let mut archivo = OpenOptions::new()
        .create(true)
        .append(true)
        .open(ruta)
        .with_context(|| format!("no se pudo abrir {ruta:?}"))?;
    writeln!(archivo, "{}", formatear(recibo))?;
    Ok(())
}

pub fn tokens_totales(ruta: &Path) -> Result<u64> {
    if !ruta.exists() {
        return Ok(0);
    }
    let archivo = std::fs::File::open(ruta)?;
    let lector = BufReader::new(archivo);
    let mut total = 0u64;
    for linea in lector.lines() {
        if let Some(recibo) = parsear(&linea?) {
            total += recibo.tokens_procesados;
        }
    }
    Ok(total)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formatear_y_parsear_son_inversos() {
        let recibo = Recibo {
            trabajo_id: "abc-123".into(),
            tokens_procesados: 42,
        };
        let linea = formatear(&recibo);
        assert_eq!(parsear(&linea), Some(recibo));
    }

    #[test]
    fn parsear_devuelve_none_para_linea_malformada() {
        assert_eq!(parsear("sin-coma"), None);
        assert_eq!(parsear("id,no-es-numero"), None);
    }

    #[test]
    fn tokens_totales_es_cero_si_el_archivo_no_existe() {
        let ruta = Path::new("/tmp/la-colmena-recibo-inexistente.log");
        assert_eq!(tokens_totales(ruta).unwrap(), 0);
    }

    #[test]
    fn registrar_y_sumar_tokens_totales() -> Result<()> {
        let ruta = std::env::temp_dir().join(format!(
            "la-colmena-recibo-test-{}.log",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&ruta);

        registrar(
            &ruta,
            &Recibo {
                trabajo_id: "t1".into(),
                tokens_procesados: 10,
            },
        )?;
        registrar(
            &ruta,
            &Recibo {
                trabajo_id: "t2".into(),
                tokens_procesados: 15,
            },
        )?;

        assert_eq!(tokens_totales(&ruta)?, 25);

        std::fs::remove_file(&ruta)?;
        Ok(())
    }
}
