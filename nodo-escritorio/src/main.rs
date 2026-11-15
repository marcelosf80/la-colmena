mod benchmark;
mod canal_trabajo;
mod cliente_coordinador;
mod control_usuario;
mod ejecutor_modelo;
mod hardware;
mod motor_servidor;
mod politicas_recursos;
mod recibo_local;

use std::path::Path;
use std::sync::atomic::{AtomicU32, Ordering};
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

    /// Prompt de respaldo cuando el coordinador no manda `prompt` en la
    /// asignación (compatibilidad con contratos viejos o pruebas locales).
    #[arg(long, default_value = "En una frase, qué es el cómputo compartido para IA:")]
    prompt_demo: String,

    /// Forzar si el nodo reporta GPU. Sin este flag se detecta con
    /// `nvidia-smi` (AMD/Intel todavía no se detectan automáticamente).
    #[arg(long)]
    tiene_gpu: Option<bool>,

    /// Tokens del benchmark de arranque para medir tokens/s reales.
    /// 0 desactiva el benchmark (se reporta 0.0).
    #[arg(long, default_value_t = 16)]
    tokens_benchmark: u32,
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

    // Métricas reales de arranque: GPU detectada (o forzada) y tokens/s
    // medidos con el motor ya cargado. Antes se reportaban valores fijos.
    let tiene_gpu = args.tiene_gpu.unwrap_or_else(hardware::detectar_gpu);
    let tokens_por_segundo = if args.tokens_benchmark > 0 {
        let medido = benchmark::medir_tokens_por_segundo(motor.as_ref(), args.tokens_benchmark);
        info!(
            tokens_por_segundo = medido,
            tokens_benchmark = args.tokens_benchmark,
            "benchmark de arranque completado"
        );
        medido
    } else {
        0.0
    };

    cliente
        .registrar(&RegistroNodo {
            nodo_id: args.nodo_id.clone(),
            ram_donada_mb: args.ram_max_mb,
            cores_donados: num_cpus_logicos(),
            tiene_gpu,
            modelo_hash: args.modelo_hash.clone(),
            posicion: args.posicion,
            tokens_por_segundo,
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

    // Trabajos que este nodo está procesando ahora mismo. Se reporta en el
    // heartbeat y es real porque la inferencia corre en tareas aparte (ver
    // el brazo de asignación más abajo).
    let en_curso = Arc::new(AtomicU32::new(0));

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
                let consultas_en_curso = en_curso.load(Ordering::Relaxed);
                match cliente
                    .enviar_heartbeat(
                        &args.nodo_id,
                        &Latido { consultas_en_curso, acepta_trabajo: true },
                    )
                    .await
                {
                    Ok(()) => info!(
                        uso_ram_mb,
                        uso_cpu_pct,
                        consultas_en_curso,
                        "heartbeat enviado al coordinador"
                    ),
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

                // Prompt real de la consulta; si el coordinador no lo manda
                // (contrato viejo), cae al `--prompt-demo` para no romper.
                let prompt = if asignacion.prompt.is_empty() {
                    prompt_demo.clone()
                } else {
                    asignacion.prompt.clone()
                };

                // La inferencia corre en una tarea aparte: así este loop
                // sigue enviando heartbeats y atendiendo el control de
                // usuario mientras el motor trabaja. Antes el `await`
                // bloqueaba el select, y una inferencia más larga que el
                // timeout de latido podía hacer que el coordinador marcara
                // al nodo como CAIDO en pleno trabajo.
                en_curso.fetch_add(1, Ordering::Relaxed);
                let motor = motor.clone();
                let emisor = emisor_resultados.clone();
                let contador = en_curso.clone();
                let archivo_recibos = args.archivo_recibos.clone();
                tokio::spawn(async move {
                    // El motor es un servidor HTTP: la llamada es bloqueante.
                    let motor_para_tokens = motor.clone();
                    let resultado = tokio::task::spawn_blocking(move || {
                        motor.procesar(&prompt.into_bytes())
                    })
                    .await;

                    let trabajo_id = asignacion.trabajo_id.clone();
                    let rol = asignacion.rol.clone();
                    match resultado {
                        Ok(Ok(activacion)) => {
                            let tokens = motor_para_tokens.tokens_de_ultima_ejecucion();
                            let texto = String::from_utf8_lossy(&activacion).into_owned();
                            info!(
                                trabajo_id = %trabajo_id,
                                tokens_generados = tokens,
                                bytes_salida = activacion.len(),
                                "asignación procesada por el motor"
                            );
                            let recibo = recibo_local::Recibo {
                                trabajo_id: trabajo_id.clone(),
                                tokens_procesados: tokens,
                            };
                            if let Err(error) =
                                recibo_local::registrar(Path::new(&archivo_recibos), &recibo)
                            {
                                warn!(%error, "no se pudo registrar el recibo local");
                            }
                            // Cada nodo ejecuta el modelo completo: el
                            // resultado que vuelve es final (no hay pipeline
                            // de activaciones entre nodos).
                            if emisor
                                .send(MensajeResultado::exitoso(
                                    trabajo_id.clone(),
                                    texto,
                                    rol,
                                    tokens,
                                ))
                                .is_err()
                            {
                                warn!(trabajo_id = %trabajo_id, "no se pudo encolar el resultado: el canal de trabajo se cerró");
                            }
                        }
                        Ok(Err(error)) => {
                            warn!(trabajo_id = %trabajo_id, %error, "el motor no pudo procesar la asignación");
                            let _ = emisor.send(MensajeResultado::fallido(
                                trabajo_id.clone(),
                                error.to_string(),
                                rol,
                            ));
                        }
                        Err(error) => {
                            warn!(%error, "la tarea del motor falló al ejecutarse");
                            let _ = emisor.send(MensajeResultado::fallido(
                                trabajo_id.clone(),
                                format!("la tarea del motor falló al ejecutarse: {error}"),
                                rol,
                            ));
                        }
                    }

                    contador.fetch_sub(1, Ordering::Relaxed);
                });
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
