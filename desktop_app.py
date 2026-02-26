"""
LLM → SCORM → Chamilo — Desktop Application.

Запускает веб-интерфейс в нативном окне Windows.

Использование:
    python desktop_app.py
"""

import logging
import sys
import threading

logger = logging.getLogger(__name__)

# Fix Windows console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def start_server():
    """Start Flask server in background thread."""
    from web_app import app
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


def main():
    try:
        import webview
    except ImportError:
        print("Ошибка: pywebview не установлен.")
        print("Выполните: pip install pywebview")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    print("=" * 50)
    print("🚀 LLM → SCORM → Chamilo — Desktop App")
    print("=" * 50)

    # Start Flask in background
    server = threading.Thread(target=start_server, daemon=True)
    server.start()

    # Wait for server to start
    import time
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:5000/")
            break
        except Exception:
            time.sleep(0.3)

    # Open native window
    webview.create_window(
        title="SCORM Generator — LLM → SCORM → Chamilo",
        url="http://127.0.0.1:5000",
        width=1200,
        height=800,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
