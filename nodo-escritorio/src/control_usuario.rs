//! El usuario debe poder pausar, reanudar o detener el nodo en cualquier
//! momento. `ControlUsuario` es la fuente de verdad de ese estado, compartida
//! entre la tarea de red y la de ejecución vía `tokio::sync::watch`.
//!
//! `reanudar` y `estado_actual` todavía no tienen llamador en `main.rs`:
//! quedan para cuando se agregue el canal de control del usuario (API local
//! o señal del sistema) en Fase 1.
#![allow(dead_code)]

use tokio::sync::watch;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EstadoControl {
    Activo,
    Pausado,
    Deteniendo,
}

pub struct ControlUsuario {
    emisor: watch::Sender<EstadoControl>,
}

impl ControlUsuario {
    pub fn nuevo() -> (Self, watch::Receiver<EstadoControl>) {
        let (emisor, receptor) = watch::channel(EstadoControl::Activo);
        (Self { emisor }, receptor)
    }

    pub fn pausar(&self) {
        let _ = self.emisor.send(EstadoControl::Pausado);
    }

    pub fn reanudar(&self) {
        let _ = self.emisor.send(EstadoControl::Activo);
    }

    pub fn detener(&self) {
        let _ = self.emisor.send(EstadoControl::Deteniendo);
    }

    pub fn estado_actual(&self) -> EstadoControl {
        *self.emisor.borrow()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arranca_activo() {
        let (control, _receptor) = ControlUsuario::nuevo();
        assert_eq!(control.estado_actual(), EstadoControl::Activo);
    }

    #[test]
    fn pausar_cambia_el_estado() {
        let (control, _receptor) = ControlUsuario::nuevo();
        control.pausar();
        assert_eq!(control.estado_actual(), EstadoControl::Pausado);
    }

    #[test]
    fn reanudar_despues_de_pausar_vuelve_a_activo() {
        let (control, _receptor) = ControlUsuario::nuevo();
        control.pausar();
        control.reanudar();
        assert_eq!(control.estado_actual(), EstadoControl::Activo);
    }

    #[test]
    fn el_receptor_ve_los_cambios_de_estado() {
        let (control, mut receptor) = ControlUsuario::nuevo();
        control.pausar();
        // `changed()` resuelve en cuanto hay un valor nuevo desde la última lectura.
        tokio_test::block_on(receptor.changed()).unwrap();
        assert_eq!(*receptor.borrow(), EstadoControl::Pausado);
    }

    #[test]
    fn detener_es_terminal_y_distinto_de_pausado() {
        let (control, _receptor) = ControlUsuario::nuevo();
        control.detener();
        assert_eq!(control.estado_actual(), EstadoControl::Deteniendo);
        assert_ne!(control.estado_actual(), EstadoControl::Pausado);
    }
}
