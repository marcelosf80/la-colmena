mod canal_trabajo;
mod cliente_coordinador;
mod control_usuario;
mod ejecutor_modelo;
mod motor_servidor;
mod politicas_recursos;
mod recibo_local;

use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use clap::Parser;
use canal_trabajo::MensajeResultado;
use cliente_coordinador::{url_websocket, ClienteCoordinador, Latido, RegistroNodo};
use control_usuario::{ControlUsuario, EstadoControl};
use ejecutor_modelo::{MotorInferencia, MotorSimulado};
use politicas_recursos::PoliticaRecursos;
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

    /// Archivo local append-only con los trabajos procesados
    #[arg(long, default_value = "recibos-colmena.log")]
    archivo_recibos: String,

    /// Ruta al binario `llama-server` oficial de llama.cpp. Si se pasa
    /// junto con `--pesos`, el nodo ejecuta inferencia REAL en lugar del
    /// motor simulado. El binario se descarga del catálogo oficial.
    #[arg(long)]
    llama_server: Option<String>,

    /// Ruta al archivo de pesos .gguf del modelo (requiere --llama-server)
    #[arg(long)]
    pesos: Option<String>,

    /// Puerto local del motor (llama-server escucha en 127.0.0.1)
    #[arg(long, default_value_t = 8718)]
    puerto_motor: u16,

    /// Prompt de demostración para procesar asignaciones mientras el
    /// protocolo de activaciones no viaje por el canal (Fase 1).
    #[arg(long, default_value = "En una frase, qué es el cómputo compartido para IA:")]
    prompt_demo: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();
    let args = Argumentos::parse();

    let politica = PoliticaRecursos::new(args.ram_max_mb, args.cpu_max_pct);
    let (control, estado_rx) = ControlUsuario::nuevo();
    let cliente = ClienteCoordinador::nuevo(args.coordinador.clone());

    // Selección de motor: real (llama-server subprocess) si el usuario pasa
    // binario + pesos; simulado en caso contrario (dev/CI, sin pesos).
    let motor: Arc<dyn MotorInferencia> = match (&args.llama_server, &args.pesos) {
        (Some(ruta_binario), Some(ruta_pesos)) => {
            let motor_real = motor_servidor::MotorServidorLlama::iniciar(
                ruta_binario,
                ruta_pesos,
                args.puerto_motor,
            )?;
            info!(
                puerto_motor = ?motor_real.puerto(),
                pesos = %ruta_pesos,
                "motor REAL de llama.cpp listo (llama-server subprocess)"
            );
            Arc::new(motor_real)
        }
        (Some(_), None) => {
            anyhow::bail!("pasaste --llama-server pero falta --pesos <ruta.gguf>");
        }
        (None, Some(_)) => {
            anyhow::bail!("pasaste --pesos pero falta --llama-server <ruta del binario>");
        }
        (None, None) => {
            let mut motor_sim = MotorSimulado::default();
            motor_sim.cargar(
                "placeholder.gguf",
                args.posicion * 8,
                args.posicion * 8 + 8,
            )?;
            info!(
                motor_capas = ?motor_sim.capas_cargadas(),
                "motor de inferencia listo (simulado: usá --llama-server + --pesos para inferencia real)"
            );
            Arc::new(motor_sim)
        }
    };
    let prompt_demo = args.prompt_demo.clone();

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

    // Canal de despacho: el coordinador empuja asignaciones por WebSocket.
    // El hilo reconecta solo; el loop principal decide si acepta el trabajo.
    let (emisor_trabajos, mut receptor_trabajos) = tokio::sync::mpsc::unbounded_channel();
    let (_canal, emisor_resultados) = canal_trabajo::iniciar(
        url_websocket(&args.coordinador, &args.nodo_id),
        emisor_trabajos,
    );

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
                    // Informar al coordinador para que no asigne trabajo:
                    // un nodo pausado equivale a CAIDO para el planificador.
                    informar_pausa(&cliente, &args.nodo_id).await;
                    continue;
                }
                if !politica.dentro_de_limite(uso_ram_mb, uso_cpu_pct) {
                    warn!(uso_ram_mb, uso_cpu_pct, "fuera de la política donada, pausando");
                    control.pausar();
                    informar_pausa(&cliente, &args.nodo_id).await;
                    continue;
                }

                // Heartbeat real: estado y carga viajan al coordinador.
                match cliente
                    .enviar_heartbeat(
                        &args.nodo_id,
                        &Latido { consultas_en_curso: 0, acepta_trabajo: true },
                    )
                    .await
                {
                    Ok(()) => info!(uso_ram_mb, uso_cpu_pct, "heartbeat enviado al coordinador"),
                    Err(error) => warn!(%error, "no se pudo enviar el heartbeat"),
                }
            }
            Some(asignacion) = receptor_trabajos.recv() => {
                info!(
                    trabajo_id = %asignacion.trabajo_id,
                    posicion = asignacion.posicion,
                    cadena = ?asignacion.cadena,
                    "asignación de trabajo recibida"
                );

                if *estado_rx.borrow() != EstadoControl::Activo {
                    warn!(trabajo_id = %asignacion.trabajo_id, "nodo pausado: asignación descartada");
                    continue;
                }

                // El motor es un servidor HTTP: la llamada es bloqueante,
                // así que corre en spawn_blocking para no frenar heartbeat
                // ni control de usuario.
                let motor = motor.clone();
                let prompt = prompt_demo.clone();
                let motor_para_tokens = motor.clone();
                let resultado = tokio::task::spawn_blocking(move || {
                    motor.procesar(&prompt.into_bytes())
                })
                .await;

                match resultado {
                    Ok(Ok(activacion)) => {
                        let tokens = motor_para_tokens.tokens_de_ultima_ejecucion();
                        let texto = String::from_utf8_lossy(&activacion).into_owned();
                        info!(
                            trabajo_id = %asignacion.trabajo_id,
                            tokens_generados = tokens,
                            bytes_salida = activacion.len(),
                            "asignación procesada por el motor"
                        );
                        let recibo = recibo_local::Recibo {
                            trabajo_id: asignacion.trabajo_id.clone(),
                            tokens_procesados: tokens,
                        };
                        if let Err(error) =
                            recibo_local::registrar(Path::new(&args.archivo_recibos), &recibo)
                        {
                            warn!(%error, "no se pudo registrar el recibo local");
                        }
                        // TODO Fase 1: si `siguiente_nodo_id` no es None,
                        // esto todavía no es el último eslabón de la cadena
                        // (pipeline multi-nodo real) — hoy cada nodo procesa
                        // el prompt de demostración de forma independiente,
                        // así que se reporta como resultado final siempre.
                        // Reenviar la activación al siguiente nodo queda
                        // pendiente como feature aparte.
                        if emisor_resultados
                            .send(MensajeResultado::exitoso(asignacion.trabajo_id.clone(), texto))
                            .is_err()
                        {
                            warn!(trabajo_id = %asignacion.trabajo_id, "no se pudo encolar el resultado: el canal de trabajo se cerró");
                        }
                    }
                    Ok(Err(error)) => {
                        warn!(trabajo_id = %asignacion.trabajo_id, %error, "el motor no pudo procesar la asignación");
                        let _ = emisor_resultados.send(MensajeResultado::fallido(
                            asignacion.trabajo_id.clone(),
                            error.to_string(),
                        ));
                    }
                    Err(error) => {
                        warn!(%error, "la tarea del motor falló al ejecutarse");
                        let _ = emisor_resultados.send(MensajeResultado::fallido(
                            asignacion.trabajo_id.clone(),
                            format!("la tarea del motor falló al ejecutarse: {error}"),
                        ));
                    }
                }
            }
            _ = &mut ctrl_c => {
                info!("señal de apagado recibida, deteniendo nodo");
                control.detener();
                // Último heartbeat: avisar que este nodo ya no acepta trabajo.
                let _ = cliente
                    .enviar_heartbeat(
                        &args.nodo_id,
                        &Latido { consultas_en_curso: 0, acepta_trabajo: false },
                    )
                    .await;
                break;
            }
        }
    }

    Ok(())
}

async fn informar_pausa(cliente: &ClienteCoordinador, nodo_id: &str) {
    if let Err(error) = cliente
        .enviar_heartbeat(
            nodo_id,
            &Latido { consultas_en_curso: 0, acepta_trabajo: false },
        )
        .await
    {
        warn!(%error, "no se pudo informar la pausa al coordinador");
    }
}

fn num_cpus_logicos() -> u32 {
    System::new_all().cpus().len() as u32
}
