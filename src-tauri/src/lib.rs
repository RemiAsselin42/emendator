use tauri_plugin_shell::ShellExt;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            } else {
                // Release builds spawn the bundled FastAPI sidecar so users never
                // start the backend by hand. In dev it is run manually (see
                // CONTRIBUTING), and the bundled binary is absent, so we skip it.
                spawn_sidecar(app.handle())?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Launch the bundled `emendator-backend` sidecar and stream its output to the log.
fn spawn_sidecar(handle: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    use tauri_plugin_shell::process::CommandEvent;

    let (mut rx, child) = handle.shell().sidecar("emendator-backend")?.spawn()?;
    tauri::async_runtime::spawn(async move {
        // Keep the child alive for as long as it runs; it stops when the app exits.
        let _child = child;
        while let Some(event) = rx.recv().await {
            if let CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) = event {
                log::info!("[sidecar] {}", String::from_utf8_lossy(&bytes));
            }
        }
    });
    Ok(())
}
