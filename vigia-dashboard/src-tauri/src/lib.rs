use std::net::TcpStream;
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

// ─── Estado compartido: proceso Flask ───────────────────────────────────────

struct FlaskState {
    child: Mutex<Child>,
}

impl FlaskState {
    fn kill(&self) {
        if let Ok(mut c) = self.child.lock() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }
}

// ─── Punto de entrada público ────────────────────────────────────────────────

pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();

            // Localizar server.py: junto al binario o en el directorio actual
            let server_py = locate_server_py();
            let workdir = server_py
                .parent()
                .unwrap_or(std::path::Path::new("."))
                .to_path_buf();

            // Arrancar Flask (VIGIA_TAURI suprime la apertura del navegador)
            let child = Command::new("python3")
                .arg(&server_py)
                .current_dir(&workdir)
                .env("VIGIA_TAURI", "1")
                .spawn()
                .expect("No se pudo arrancar server.py — ¿está Python 3 instalado?");

            app.manage(Arc::new(FlaskState {
                child: Mutex::new(child),
            }));

            // Esperar a Flask en hilo secundario y luego abrir la ventana
            thread::spawn(move || {
                if wait_for_port(5000, 30) {
                    // Capturar el icono antes de mover handle al builder
                    let icon = handle.default_window_icon().cloned();
                    if let Ok(window) = WebviewWindowBuilder::new(
                        &handle,
                        "main",
                        WebviewUrl::External("http://localhost:5000".parse().unwrap()),
                    )
                    .title("VIGIA — Panel del Profesor")
                    .inner_size(1280.0, 800.0)
                    .center()
                    .build()
                    {
                        // Aplicar icono a la ventana para que aparezca en la barra de tareas
                        if let Some(icon) = icon {
                            let _ = window.set_icon(icon);
                        }
                    }
                } else {
                    eprintln!("[VIGIA] Tiempo de espera agotado: Flask no respondió en 30 s");
                    handle.exit(1);
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Error al construir la aplicación VIGIA");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<Arc<FlaskState>>() {
                state.kill();
            }
        }
    });
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/// Busca server.py junto al binario, luego en el directorio de trabajo.
fn locate_server_py() -> std::path::PathBuf {
    // 1) Junto al ejecutable (instalación normal en /opt/vigia/)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let candidate = dir.join("server.py");
            if candidate.exists() {
                return candidate;
            }
        }
    }
    // 2) Directorio de trabajo (desarrollo: cargo run desde vigia-master/)
    let candidate = std::path::PathBuf::from("server.py");
    if candidate.exists() {
        return candidate;
    }
    // 3) Dos niveles arriba del binario (dev: target/debug/ → raíz del repo)
    if let Ok(exe) = std::env::current_exe() {
        for ancestor in exe.ancestors().skip(1) {
            let c = ancestor.join("server.py");
            if c.exists() {
                return c;
            }
        }
    }
    // Fallback — dejará que Python falle con mensaje descriptivo
    std::path::PathBuf::from("server.py")
}

/// Sondea el puerto hasta que responda o se agote el tiempo.
fn wait_for_port(port: u16, timeout_secs: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}
