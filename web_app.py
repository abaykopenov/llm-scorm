"""
LLM → SCORM → Chamilo Pipeline — Web UI.

Запуск:
    python web_app.py
    Откройте http://localhost:5000
"""

import json
import os
import sys
import threading

from flask import Flask, jsonify, request, send_file, send_from_directory

# ─── Fix Windows console encoding ───
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

app = Flask(__name__, static_folder="static", static_url_path="/static")

# In-memory state
_state = {
    "last_course_json": None,
    "last_scorm_path": None,
    "generating": False,
}


# ═══════════════════════════════════════════
#  Static Pages
# ═══════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ═══════════════════════════════════════════
#  Settings
# ═══════════════════════════════════════════

@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Return current .env settings (passwords masked)."""
    import config
    # Force reload
    from importlib import reload
    reload(config)

    return jsonify({
        "chamilo_url": config.CHAMILO_URL,
        "chamilo_user": config.CHAMILO_USER,
        "chamilo_password": "••••" if config.CHAMILO_PASSWORD else "",
        "llm_base_url": config.OPENAI_BASE_URL,
        "llm_model": config.OPENAI_MODEL,
        "llm_api_key": "••••" if config.OPENAI_API_KEY else "",
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

    return jsonify({"ok": True})


# ═══════════════════════════════════════════
#  Connection Tests
# ═══════════════════════════════════════════

@app.route("/api/test-chamilo", methods=["POST"])
def test_chamilo():
    """Test Chamilo LMS connection and login."""
    data = request.json
    import config
    from importlib import reload
    reload(config)
    url = (data.get("url", "") or config.CHAMILO_URL).rstrip("/")
    user = data.get("user", "") or config.CHAMILO_USER or "admin"
    password = data.get("password", "") or config.CHAMILO_PASSWORD

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
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/chamilo-courses", methods=["POST"])
def chamilo_courses():
    """Get list of courses from Chamilo."""
    import config
    from importlib import reload
    reload(config)

    data = request.json
    url = (data.get("url", "") or config.CHAMILO_URL).rstrip("/")
    user = data.get("user", "") or config.CHAMILO_USER or "admin"
    password = data.get("password", "") or config.CHAMILO_PASSWORD

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
        return jsonify({"ok": False, "courses": [], "error": str(e)[:200]})


# ═══════════════════════════════════════════
#  Course Generation
# ═══════════════════════════════════════════

@app.route("/api/generate", methods=["POST"])
def generate_course():
    """Generate course via LLM (Multi-step)."""
    if _state["generating"]:
        return jsonify({"ok": False, "error": "Генерация уже запущена"})

    data = request.json
    topic = data.get("topic", "")
    lang = data.get("lang", "ru")
    base_url = data.get("base_url", "")
    model = data.get("model", "")
    api_key = data.get("api_key", "")

    # Advanced settings (Hierarchy)
    num_modules = int(data.get("num_modules", 1))
    sections_per_module = int(data.get("sections_per_module", 1))
    scos_per_section = int(data.get("scos_per_section", 1))
    screens_per_sco = int(data.get("screens_per_sco", 2))
    questions_per_sco = int(data.get("questions_per_sco", 1))
    final_test_questions = int(data.get("final_test_questions", 3))

    temperature = float(data.get("temperature", 0.7))
    max_tokens = int(data.get("max_tokens", 4096))
    detail_level = data.get("detail_level", "normal")

    if not topic:
        return jsonify({"ok": False, "error": "Укажите тему курса"})

    _state["generating"] = True
    _state["progress_msg"] = "Инициализация..."
    _state["progress_pct"] = 0
    _state["last_error"] = None

    def bg_generate():
        try:
            from llm_generator import LLMCourseGenerator
            generator = LLMCourseGenerator(
                api_key=api_key or None,
                model=model or None,
                base_url=base_url or None,
            )

            def prog_cb(msg, pct):
                _state["progress_msg"] = msg
                _state["progress_pct"] = pct

            course = generator.generate_course(
                topic=topic,
                language=lang,
                num_modules=num_modules,
                sections_per_module=sections_per_module,
                scos_per_section=scos_per_section,
                screens_per_sco=screens_per_sco,
                questions_per_sco=questions_per_sco,
                final_test_questions=final_test_questions,
                detail_level=detail_level,
                temperature=temperature,
                max_tokens=max_tokens,
                progress_callback=prog_cb
            )

            _state["last_course_json"] = course
            _state["progress_msg"] = "Готово!"
            _state["progress_pct"] = 100
        except Exception as e:
            err = str(e)
            if "insufficient_quota" in err: err = "Квота OpenAI исчерпана. Проверьте баланс."
            elif "Connection" in err or "connect" in err.lower(): err = "Не удалось подключиться к LLM-серверу."
            _state["last_error"] = err[:300]
        finally:
            _state["generating"] = False

    t = threading.Thread(target=bg_generate)
    t.daemon = True
    t.start()

    return jsonify({"ok": True, "message": "Генерация запущена"})


@app.route("/api/generate-status", methods=["GET"])
def generate_status():
    if _state.get("last_error"):
        return jsonify({"ok": False, "error": _state["last_error"], "generating": False})
    
    return jsonify({
        "ok": True,
        "generating": _state.get("generating", False),
        "msg": _state.get("progress_msg", ""),
        "pct": _state.get("progress_pct", 0),
        "course": _state.get("last_course_json") if not _state.get("generating") and _state.get("progress_pct") == 100 else None
    })


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
        return jsonify({"ok": False, "error": str(e)[:300]})


@app.route("/api/upload", methods=["POST"])
def upload_to_chamilo():
    """Upload SCORM to Chamilo."""
    import config
    from importlib import reload
    reload(config)

    data = request.json
    scorm_path = _state.get("last_scorm_path")
    if not scorm_path:
        return jsonify({"ok": False, "error": "Сначала соберите SCORM"})

    course_code = data.get("course_code", "")

    try:
        from chamilo_uploader import ChamiloUploader
        uploader = ChamiloUploader(
            chamilo_url=data.get("chamilo_url") or config.CHAMILO_URL,
            username=data.get("chamilo_user") or config.CHAMILO_USER,
            password=data.get("chamilo_password") or config.CHAMILO_PASSWORD,
        )
        success = uploader.upload(scorm_path, course_code or None)
        if success:
            return jsonify({"ok": True, "message": "SCORM загружен в Chamilo!"})
        else:
            return jsonify({"ok": False, "error": "Не удалось загрузить. Попробуйте вручную."})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]})


@app.route("/api/download/<filename>")
def download_file(filename):
    """Download generated SCORM ZIP."""
    import config
    path = os.path.join(config.OUTPUT_DIR, filename)
    if os.path.isfile(path):
        return send_file(path, as_attachment=True)
    return jsonify({"error": "File not found"}), 404


# ═══════════════════════════════════════════
#  History & JSON Editor & Preview
# ═══════════════════════════════════════════

@app.route("/api/history")
def history():
    """List generated SCORM packages from output directory."""
    import config
    output_dir = config.OUTPUT_DIR
    if not os.path.isdir(output_dir):
        return jsonify({"ok": True, "items": []})

    items = []
    for f in sorted(os.listdir(output_dir), reverse=True):
        if f.endswith(".zip"):
            fpath = os.path.join(output_dir, f)
            stat = os.stat(fpath)
            items.append({
                "filename": f,
                "size_kb": round(stat.st_size / 1024, 1),
                "created": stat.st_mtime,
            })

    return jsonify({"ok": True, "items": items[:20]})  # Last 20


@app.route("/api/course-json")
def get_course_json():
    """Return current course JSON for the editor."""
    course = _state.get("last_course_json")
    if not course:
        return jsonify({"ok": False, "error": "No course"})
    return jsonify({"ok": True, "course": course})


@app.route("/api/update-course", methods=["POST"])
def update_course():
    """Update course JSON from the editor, then rebuild SCORM."""
    data = request.json
    course = data.get("course")
    if not course:
        return jsonify({"ok": False, "error": "JSON not provided"})

    # Validate
    from llm_generator import LLMCourseGenerator
    errors = LLMCourseGenerator.validate_course_json(course)
    if errors:
        return jsonify({"ok": False, "error": "; ".join(errors[:5])})

    _state["last_course_json"] = course

    # Auto-rebuild SCORM
    try:
        from scorm_builder import SCORMBuilder
        builder = SCORMBuilder()
        path = builder.build(course)
        _state["last_scorm_path"] = path
        filename = os.path.basename(path)
        return jsonify({"ok": True, "course": course, "filename": filename})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]})


@app.route("/api/preview-scorm")
def preview_scorm():
    """Serve SCORM HTML preview (renders index.html from template)."""
    course = _state.get("last_course_json")
    if not course:
        return "<html><body><h2>No course generated yet</h2></body></html>", 200

    try:
        from jinja2 import Environment, FileSystemLoader
        import config
        env = Environment(
            loader=FileSystemLoader(config.TEMPLATES_DIR),
            autoescape=False,
        )
        template = env.get_template("index.html")
        html = template.render(
            title=course.get("title", "Untitled"),
            description=course.get("description", ""),
            language=course.get("language", "ru"),
            pages=course.get("pages", []),
        )
        return html, 200
    except Exception as e:
        return f"<html><body><h2>Error: {e}</h2></body></html>", 500


# ═══════════════════════════════════════════
#  Run
# ═══════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    try:
        print("LLM -> SCORM -> Chamilo -- Web UI")
    except UnicodeEncodeError:
        print("LLM -> SCORM -> Chamilo -- Web UI")
    print("   http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)

