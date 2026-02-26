"""
LLM → SCORM → Chamilo Pipeline — Web UI.

Запуск:
    python web_app.py
    Откройте http://localhost:5000
"""

import json
import logging
import os
import sys
import threading
import uuid

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

import config

# ─── Fix Windows console encoding ───
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─── Logging (#16) ───
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", static_url_path="/static")

# In-memory state
_state = {
    "last_course_json": None,
    "last_scorm_path": None,
}

# Async tasks store (#4)
_tasks = {}


# ═══════════════════════════════════════════
#  Static Pages
# ═══════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ═══════════════════════════════════════════
#  Settings (#3 — thread-safe config)
# ═══════════════════════════════════════════

@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Return current .env settings (passwords masked)."""
    cfg = config.get_config()

    return jsonify({
        "chamilo_url": cfg["CHAMILO_URL"],
        "chamilo_user": cfg["CHAMILO_USER"],
        "chamilo_password": "••••" if cfg["CHAMILO_PASSWORD"] else "",
        "llm_base_url": cfg["OPENAI_BASE_URL"],
        "llm_model": cfg["OPENAI_MODEL"],
        "llm_api_key": "••••" if cfg["OPENAI_API_KEY"] else "",
    })


@app.route("/api/settings", methods=["POST"])
def save_settings():
    """Save settings to .env file."""
    data = request.json
    env_path = os.path.join(os.path.dirname(__file__), ".env")

    lines = []
    lines.append("# LLM → SCORM → Chamilo Pipeline\n")

    if data.get("llm_base_url"):
        lines.append(f"OPENAI_BASE_URL={data['llm_base_url']}\n")
    if data.get("llm_model"):
        lines.append(f"OPENAI_MODEL={data['llm_model']}\n")
    if data.get("llm_api_key") and data["llm_api_key"] != "••••":
        lines.append(f"OPENAI_API_KEY={data['llm_api_key']}\n")

    if data.get("chamilo_url"):
        lines.append(f"CHAMILO_URL={data['chamilo_url']}\n")
    if data.get("chamilo_user"):
        lines.append(f"CHAMILO_USER={data['chamilo_user']}\n")
    if data.get("chamilo_password") and data["chamilo_password"] != "••••":
        lines.append(f"CHAMILO_PASSWORD={data['chamilo_password']}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Reload dotenv
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass

    logger.info("Settings saved to .env")
    return jsonify({"ok": True})


# ═══════════════════════════════════════════
#  Connection Tests
# ═══════════════════════════════════════════

@app.route("/api/test-chamilo", methods=["POST"])
def test_chamilo():
    """Test Chamilo LMS connection and login."""
    data = request.json
    cfg = config.get_config()
    url = (data.get("url", "") or cfg["CHAMILO_URL"]).rstrip("/")
    user = data.get("user", "") or cfg["CHAMILO_USER"] or "admin"
    password = data.get("password", "") or cfg["CHAMILO_PASSWORD"]

    if not url:
        return jsonify({"ok": False, "error": "URL не указан"})

    try:
        import requests as req
        # Test connectivity
        resp = req.get(f"{url}/index.php", timeout=10)
        if resp.status_code != 200:
            return jsonify({"ok": False, "error": f"HTTP {resp.status_code}"})

        # Test login
        session = req.Session()
        session.get(f"{url}/index.php", timeout=10)

        resp = session.post(f"{url}/index.php", data={
            "login": user,
            "password": password,
            "submitAuth": "1",
        }, timeout=10, allow_redirects=True)

        if "logout" in resp.text.lower() or user.lower() in resp.text.lower():
            return jsonify({"ok": True, "message": f"Подключено как {user}"})
        else:
            return jsonify({"ok": False, "error": "Неверный логин/пароль"})

    except Exception as e:
        logger.warning("Chamilo test failed: %s", e)
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/test-llm", methods=["POST"])
def test_llm():
    """Test LLM connection (OpenAI-compatible API)."""
    data = request.json
    base_url = data.get("base_url", "")
    model = data.get("model", "")
    api_key = data.get("api_key", "")

    if not base_url and not api_key:
        return jsonify({"ok": False, "error": "Укажите URL сервера или API ключ"})

    try:
        import requests as req

        if base_url:
            # Ollama / LM Studio / vLLM
            # Strip /v1 to get base ollama URL
            ollama_base = base_url.replace("/v1", "").rstrip("/")
            resp = req.get(ollama_base, timeout=10)
            if "ollama" in resp.text.lower() or resp.status_code == 200:
                # Try to list models
                models = []
                try:
                    resp2 = req.get(f"{ollama_base}/api/tags", timeout=10)
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        models = [m["name"] for m in data2.get("models", [])]
                except Exception:
                    pass

                msg = "Сервер доступен"
                if models:
                    msg += f" ({len(models)} моделей: {', '.join(models[:5])})"
                if model:
                    if any(model in m for m in models):
                        msg += f"\n✅ Модель {model} найдена"
                    elif models:
                        msg += f"\n⚠️ Модель {model} не найдена"

                return jsonify({"ok": True, "message": msg, "models": models})
            else:
                return jsonify({"ok": False, "error": "Не OpenAI-совместимый сервер"})
        else:
            # OpenAI API
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            models = client.models.list()
            return jsonify({"ok": True, "message": "OpenAI API подключен"})

    except Exception as e:
        logger.warning("LLM test failed: %s", e)
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/chamilo-courses", methods=["POST"])
def chamilo_courses():
    """Get list of courses from Chamilo."""
    cfg = config.get_config()

    data = request.json
    url = (data.get("url", "") or cfg["CHAMILO_URL"]).rstrip("/")
    user = data.get("user", "") or cfg["CHAMILO_USER"] or "admin"
    password = data.get("password", "") or cfg["CHAMILO_PASSWORD"]

    if not url:
        return jsonify({"ok": False, "courses": []})

    try:
        import re
        import requests as req
        session = req.Session()
        session.get(f"{url}/index.php", timeout=10)
        session.post(f"{url}/index.php", data={
            "login": user, "password": password, "submitAuth": "1",
        }, timeout=10, allow_redirects=True)

        # Get courses
        resp = session.get(f"{url}/user_portal.php", timeout=10)
        matches = re.findall(r'/courses/([A-Z0-9_]+)/index\.php', resp.text, re.IGNORECASE)
        courses = list(set(matches))

        if not courses:
            resp = session.get(f"{url}/main/admin/course_list.php", timeout=10)
            matches = re.findall(r'course_code=([A-Z0-9_]+)', resp.text, re.IGNORECASE)
            courses = list(set(matches))

        return jsonify({"ok": True, "courses": courses})

    except Exception as e:
        logger.warning("Chamilo courses fetch failed: %s", e)
        return jsonify({"ok": False, "courses": [], "error": str(e)[:200]})


# ═══════════════════════════════════════════
#  Course Generation (#4 — async)
# ═══════════════════════════════════════════

def _generate_bg(task_id: str, params: dict):
    """Background thread for course generation."""
    task = _tasks[task_id]
    try:
        task["progress"] = 5
        task["status_text"] = "Подключение к LLM..."

        from llm_generator import LLMCourseGenerator
        generator = LLMCourseGenerator(
            api_key=params.get("api_key") or None,
            model=params.get("model") or None,
            base_url=params.get("base_url") or None,
        )

        task["progress"] = 15
        task["status_text"] = "Генерация курса через ИИ..."

        course = generator.generate_course(
            topic=params["topic"],
            num_pages=params.get("pages", 3),
            language=params.get("lang", "ru"),
            temperature=params.get("temperature", 0.7),
            max_tokens=params.get("max_tokens", 4096),
            blocks_per_page=params.get("blocks_per_page", 3),
            questions_per_page=params.get("questions_per_page", 1),
            detail_level=params.get("detail_level", "normal"),
            system_prompt=params.get("system_prompt") or None,
            extra_instructions=params.get("extra_instructions") or None,
        )

        task["progress"] = 70
        task["status_text"] = "Сборка SCORM-пакета..."

        # Auto-build SCORM
        from scorm_builder import SCORMBuilder
        builder = SCORMBuilder()
        scorm_path = builder.build(course)

        task["progress"] = 100
        task["status_text"] = "Готово!"
        task["status"] = "done"
        task["course"] = course
        task["scorm_path"] = scorm_path
        task["scorm_filename"] = os.path.basename(scorm_path)

        # Update global state for backward compat
        _state["last_course_json"] = course
        _state["last_scorm_path"] = scorm_path

        logger.info("Course generated: %s", course.get("title", "?"))

    except Exception as e:
        task["status"] = "error"
        task["progress"] = 0
        err = str(e)
        if "insufficient_quota" in err:
            err = "Квота OpenAI исчерпана. Проверьте баланс."
        elif "Connection" in err or "connect" in err.lower():
            err = "Не удалось подключиться к LLM-серверу."
        task["error"] = err[:300]
        task["status_text"] = "Ошибка"
        logger.error("Course generation failed: %s", e)


@app.route("/api/generate", methods=["POST"])
def generate_course():
    """Generate course via LLM (async, returns task_id)."""
    data = request.json
    topic = data.get("topic", "")

    if not topic:
        return jsonify({"ok": False, "error": "Укажите тему курса"})

    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "status": "running",
        "progress": 0,
        "status_text": "Запуск...",
        "course": None,
        "scorm_path": None,
        "scorm_filename": None,
        "error": None,
    }

    params = {
        "topic": topic,
        "pages": int(data.get("pages", 3)),
        "lang": data.get("lang", "ru"),
        "base_url": data.get("base_url", ""),
        "model": data.get("model", ""),
        "api_key": data.get("api_key", ""),
        "temperature": float(data.get("temperature", 0.7)),
        "max_tokens": int(data.get("max_tokens", 4096)),
        "blocks_per_page": int(data.get("blocks_per_page", 3)),
        "questions_per_page": int(data.get("questions_per_page", 1)),
        "detail_level": data.get("detail_level", "normal"),
        "system_prompt": data.get("system_prompt", ""),
        "extra_instructions": data.get("extra_instructions", ""),
    }

    thread = threading.Thread(target=_generate_bg, args=(task_id, params), daemon=True)
    thread.start()

    return jsonify({"ok": True, "task_id": task_id})


@app.route("/api/generate-status/<task_id>")
def generate_status(task_id):
    """Poll generation task status (#4)."""
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Задача не найдена"}), 404

    result = {
        "ok": True,
        "status": task["status"],
        "progress": task["progress"],
        "status_text": task["status_text"],
    }

    if task["status"] == "done":
        result["course"] = task["course"]
        result["scorm_filename"] = task["scorm_filename"]
    elif task["status"] == "error":
        result["error"] = task["error"]

    return jsonify(result)


@app.route("/api/generate-from-json", methods=["POST"])
def generate_from_json():
    """Load course from uploaded JSON."""
    data = request.json
    course = data.get("course")
    if not course:
        return jsonify({"ok": False, "error": "JSON не предоставлен"})

    _state["last_course_json"] = course
    return jsonify({"ok": True, "course": course})


# ═══════════════════════════════════════════
#  SCORM Build & Upload
# ═══════════════════════════════════════════

@app.route("/api/build-scorm", methods=["POST"])
def build_scorm():
    """Build SCORM package from last generated course."""
    course = _state.get("last_course_json")
    if not course:
        return jsonify({"ok": False, "error": "Сначала сгенерируйте курс"})

    try:
        from scorm_builder import SCORMBuilder
        builder = SCORMBuilder()
        path = builder.build(course)
        _state["last_scorm_path"] = path

        filename = os.path.basename(path)
        return jsonify({"ok": True, "path": path, "filename": filename})

    except Exception as e:
        logger.error("SCORM build failed: %s", e)
        return jsonify({"ok": False, "error": str(e)[:300]})


@app.route("/api/upload", methods=["POST"])
def upload_to_chamilo():
    """Upload SCORM to Chamilo."""
    cfg = config.get_config()

    data = request.json
    scorm_path = _state.get("last_scorm_path")
    if not scorm_path:
        return jsonify({"ok": False, "error": "Сначала соберите SCORM"})

    course_code = data.get("course_code", "")

    try:
        from chamilo_uploader import ChamiloUploader
        uploader = ChamiloUploader(
            chamilo_url=data.get("chamilo_url") or cfg["CHAMILO_URL"],
            username=data.get("chamilo_user") or cfg["CHAMILO_USER"],
            password=data.get("chamilo_password") or cfg["CHAMILO_PASSWORD"],
        )
        success = uploader.upload(scorm_path, course_code or None)
        if success:
            return jsonify({"ok": True, "message": "SCORM загружен в Chamilo!"})
        else:
            return jsonify({"ok": False, "error": "Не удалось загрузить. Попробуйте вручную."})

    except Exception as e:
        logger.error("Chamilo upload failed: %s", e)
        return jsonify({"ok": False, "error": str(e)[:300]})


@app.route("/api/download/<filename>")
def download_file(filename):
    """Download generated SCORM ZIP (#17 — secure_filename)."""
    filename = secure_filename(filename)
    if not filename:
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(
        config.OUTPUT_DIR, filename, as_attachment=True
    )


# ═══════════════════════════════════════════
#  Run
# ═══════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    logger.info("=" * 50)
    logger.info("🚀 LLM → SCORM → Chamilo — Web UI")
    logger.info("   http://localhost:5000")
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
