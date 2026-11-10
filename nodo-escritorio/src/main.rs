mod cliente_coordinador;
mod control_usuario;
mod ejecutor_modelo;
mod politicas_recursos;
mod recibo_local;

use clap::Parser;
use cliente_coordinador::{ClienteCoordinador, RegistroNodo};
use control_usuario::{ControlUsuario, EstadoControl};
use ejecutor_modelo::{MotorInferencia, MotorSimulado};
use politicas_recursos::PoliticaRecursos;
use std::time::Duration;
use sysinfo::System;
use tracing::{info, warn};

/// Nodo de cómputo donado para la red La Colmena.
#[derive(Parser, Debug)]
#[command(version, about)]
struct Argumentos {
    /// URL base del coordinador, ej. http://localhost:8000
    #[arg(long, default_value = "http://localhost:8000")]
    coordinador: String,

    /// Identificador único de este nodo
    #[arg(long)]
    nodo_id: String,

    /// Hash del modelo que este nodo va a servir
    #[arg(long)]
    modelo_hash: String,

    /// Posición (bloque de capas) que este nodo carga
    #[arg(long)]
    posicion: u32,

    /// RAM máxima a donar, en MB
    #[arg(long, default_value_t = 2048)]
    ram_max_mb: u64,

    /// CPU máxima a donar, en porcentaje (0-100)
    #[arg(long, default_value_t = 50.0)]
    cpu_max_pct: f32,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();
    let args = Argumentos::parse();

    let politica = PoliticaRecursos::new(args.ram_max_mb, args.cpu_max_pct);
    let (control, estado_rx) = ControlUsuario::nuevo();
    let cliente = ClienteCoordinador::nuevo(args.coordinador.clone());

    // Placeholder: en la implementación real, `capas_desde`/`capas_hasta`
    // salen del catálogo de modelos según `args.posicion`, y el motor real
    // (MotorLlamaCpp) carga los pesos desde disco con esas capas.
    let mut motor = MotorSimulado::default();
    motor.cargar("placeholder.gguf", args.posicion * 8, args.posicion * 8 + 8)?;
    info!(motor_capas = ?motor.capas_cargadas(), "motor de inferencia listo (simulado)");

    cliente
        .registrar(&RegistroNodo {
            nodo_id: args.nodo_id.clone(),
            ram_donada_mb: args.ram_max_mb,
            cores_donados: num_cpus_logicos(),
            tiene_gpu: false,
            modelo_hash: args.modelo_hash.clone(),
            posicion: args.posicion,
            tokens_por_segundo: 0.0, // TODO: benchmark real al conectar
        })
        .await?;
    info!(nodo_id = %args.nodo_id, "registrado en el coordinador");

    let ctrl_c = tokio::signal::ctrl_c();
    tokio::pin!(ctrl_c);

    let mut sistema = System::new_all();
    let mut intervalo = tokio::time::interval(Duration::from_secs(10));

    loop {
        tokio::select! {
            _ = intervalo.tick() => {
                sistema.refresh_all();
                let uso_ram_mb = sistema.used_memory() / 1024 / 1024;
                let uso_cpu_pct = sistema.global_cpu_info().cpu_usage();

                if *estado_rx.borrow() == EstadoControl::Pausado {
                    info!("nodo pausado por el usuario, sin aceptar trabajo");
                    continue;
                }
                if !politica.dentro_de_limite(uso_ram_mb, uso_cpu_pct) {
                    warn!(uso_ram_mb, uso_cpu_pct, "fuera de la política donada, pausando");
                    control.pausar();
                    continue;
                }
                info!(uso_ram_mb, uso_cpu_pct, "heartbeat ok");
                // TODO Fase 1: enviar heartbeat real al coordinador y recibir
                // trabajo asignado por WebSocket.
            }
            _ = &mut ctrl_c => {
                info!("señal de apagado recibida, deteniendo nodo");
                control.detener();
                break;
            }
        }
    }

    Ok(())
}

fn num_cpus_logicos() -> u32 {
    System::new_all().cpus().len() as u32
}
