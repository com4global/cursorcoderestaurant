#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      // iOS WKWebView: enable inline media playback and remove the
      // user-action gate so getUserMedia() and Audio playback work.
      #[cfg(target_os = "ios")]
      {
        use objc::runtime::Object;
        use objc::{msg_send, sel, sel_impl};
        use tauri::Manager;

        if let Some(window) = app.get_webview_window("main") {
          let _ = window.with_webview(move |webview: tauri::webview::PlatformWebview| unsafe {
            let wk: *mut Object = webview.inner() as *mut Object;
            let cfg: *mut Object = msg_send![wk, configuration];

            // Allow <audio>/<video> to play inline (not fullscreen-only)
            let yes: objc::runtime::BOOL = objc::runtime::YES;
            let _: () = msg_send![cfg, setAllowsInlineMediaPlayback: yes];

            // No user gesture needed before media can play (0 = WKAudiovisualMediaTypeNone)
            let _: () = msg_send![cfg, setMediaTypesRequiringUserActionForPlayback: 0u64];
          });
        }
      }

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
