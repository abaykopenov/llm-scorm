"""
Chamilo LMS Installer — Web UI для установки Chamilo на удалённый сервер.

Запуск:
    python chamilo_installer_app.py
    → Desktop окно или http://localhost:5001
"""

import json
import logging
import os
import re
import sys
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

logger = logging.getLogger(__name__)

# Fix Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

app = Flask(__name__, static_folder="static_installer", static_url_path="/static")


def _sanitize_db_param(value: str, param_name: str = "parameter") -> str:
    """Валидация параметров БД против SQL-инъекций (#1).

    Разрешены только буквы, цифры и подчёркивания.
    """
    if not re.match(r'^[a-zA-Z0-9_]+$', value):
        raise ValueError(
            f"Недопустимые символы в {param_name}: '{value}'. "
            f"Разрешены только буквы, цифры и подчёркивания."
        )
    return value


def _sanitize_db_password(value: str) -> str:
    """Экранирование пароля БД для безопасной передачи в shell (#1)."""
    # Убираем символы, которые могут сломать shell-команду
    dangerous = set('\'"`;|&$(){}[]\\\n\r')
    if any(c in dangerous for c in value):
        raise ValueError(
            "Пароль БД содержит недопустимые символы. "
            "Используйте буквы, цифры и символы: !@#%^*-_+=.,?"
        )
    return value

# In-memory state
_state = {
    "installing": False,
    "logs": [],
    "progress": 0,
    "status": "idle",  # idle, running, done, error
}


# ═══════════════════════════════════════════
#  Pages
# ═══════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static_installer", "index.html")


# ═══════════════════════════════════════════
#  SSH Test
# ═══════════════════════════════════════════

@app.route("/api/test-ssh", methods=["POST"])
def test_ssh():
    """Test SSH connection to server."""
    data = request.json
    host = data.get("host", "")
    port = int(data.get("port", 22))
    user = data.get("user", "root")
    password = data.get("password", "")

    if not host:
        return jsonify({"ok": False, "error": "IP сервера не указан"})

    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=user, password=password, timeout=10)

        # Get OS info
        _, stdout, _ = ssh.exec_command("cat /etc/os-release | head -2")
        os_info = stdout.read().decode().strip()

        # Check if Chamilo already installed
        _, stdout, _ = ssh.exec_command("test -d /var/www/html/chamilo && echo 'EXISTS' || echo 'NO'")
        chamilo_exists = "EXISTS" in stdout.read().decode()

        ssh.close()

        msg = f"Подключено к {host}"
        if os_info:
            for line in os_info.split("\n"):
                if "PRETTY_NAME" in line:
                    msg += f"\nОС: {line.split('=')[1].strip('\"')}"
        if chamilo_exists:
            msg += "\n⚠️ Chamilo уже установлен на сервере"

        return jsonify({"ok": True, "message": msg, "chamilo_exists": chamilo_exists})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


# ═══════════════════════════════════════════
#  Install
# ═══════════════════════════════════════════

@app.route("/api/install", methods=["POST"])
def install_chamilo():
    """Start Chamilo installation via SSH."""
    if _state["installing"]:
        return jsonify({"ok": False, "error": "Установка уже запущена"})

    data = request.json
    _state["installing"] = True
    _state["logs"] = []
    _state["progress"] = 0
    _state["status"] = "running"

    thread = threading.Thread(target=_run_install, args=(data,), daemon=True)
    thread.start()

    return jsonify({"ok": True})


@app.route("/api/install-status")
def install_status():
    """Get installation progress."""
    return jsonify({
        "status": _state["status"],
        "progress": _state["progress"],
        "logs": _state["logs"][-50:],  # Last 50 lines
        "log_count": len(_state["logs"]),
    })


def _log(msg):
    _state["logs"].append(msg)
    print(msg)


def _run_install(data):
    """Run installation in background thread."""
    try:
        import paramiko

        host = data.get("host", "")
        port = int(data.get("port", 22))
        ssh_user = data.get("ssh_user", "root")
        ssh_pass = data.get("ssh_password", "")

        # Chamilo params
        chamilo_ver = data.get("chamilo_ver", "1.11.26")
        db_name = data.get("db_name", "chamilo_db")
        db_user = data.get("db_user", "chamilo_user")
        db_pass = data.get("db_pass", "StrongPassword123!")
        admin_login = data.get("admin_login", "admin")
        admin_pass = data.get("admin_pass", "admin123")
        admin_email = data.get("admin_email", "admin@example.com")
        platform_lang = data.get("platform_lang", "russian")

        # Валидация параметров БД (#1 — защита от SQL-инъекций)
        try:
            db_name = _sanitize_db_param(db_name, "db_name")
            db_user = _sanitize_db_param(db_user, "db_user")
            db_pass = _sanitize_db_password(db_pass)
            admin_login = _sanitize_db_param(admin_login, "admin_login")
        except ValueError as e:
            _log(f"❌ {e}")
            _state["status"] = "error"
            _state["installing"] = False
            return

        _log(f"🔗 Подключение к {host}...")
        _state["progress"] = 5

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=ssh_user, password=ssh_pass, timeout=30)

        def run_cmd(cmd, desc="", progress=None):
            """Execute command via SSH and log output."""
            if desc:
                _log(f"📦 {desc}")
            if progress:
                _state["progress"] = progress

            _, stdout, stderr = ssh.exec_command(cmd, timeout=600)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode(errors="replace").strip()
            errors = stderr.read().decode(errors="replace").strip()

            if output:
                for line in output.split("\n")[-5:]:
                    _log(f"   {line}")
            if exit_code != 0 and errors:
                for line in errors.split("\n")[-3:]:
                    _log(f"   ⚠️ {line}")

            return exit_code, output

        _log("✅ Подключено")
        _state["progress"] = 8

        # Step 1: Update packages
        run_cmd("apt-get update -qq", "Обновление списка пакетов...", 10)

        # Step 2: Find PHP version
        _log("🔍 Определение версии PHP...")
        _state["progress"] = 15
        code, output = run_cmd("apt-cache search php | grep -oP 'php[0-9]+\\.[0-9]+' | sort -V | tail -1")
        php_ver = output.strip() if code == 0 and output.strip() else "php8.1"
        if not php_ver.startswith("php"):
            php_ver = "php8.1"
        php_short = php_ver.replace("php", "")
        _log(f"   PHP версия: {php_short}")

        # Step 3: Install dependencies
        run_cmd(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
            f"apache2 mariadb-server "
            f"{php_ver} {php_ver}-mysql {php_ver}-xml {php_ver}-mbstring "
            f"{php_ver}-gd {php_ver}-intl {php_ver}-curl {php_ver}-zip "
            f"{php_ver}-ldap {php_ver}-soap {php_ver}-bcmath "
            f"libapache2-mod-{php_ver} unzip wget curl 2>&1 | tail -5",
            "Установка Apache, MariaDB, PHP...", 20
        )

        # Step 4: Start services
        run_cmd("systemctl enable --now apache2 mariadb", "Запуск служб...", 30)

        # Step 5: Create database
        _log("🗄️ Создание базы данных...")
        _state["progress"] = 35
        run_cmd(f"mysql -e \"DROP DATABASE IF EXISTS {db_name};\"")
        run_cmd(f"mysql -e \"CREATE DATABASE {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\"")
        run_cmd(f"mysql -e \"DROP USER IF EXISTS '{db_user}'@'localhost';\"")
        run_cmd(f"mysql -e \"CREATE USER '{db_user}'@'localhost' IDENTIFIED BY '{db_pass}';\"")
        run_cmd(f"mysql -e \"GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'localhost';\"")
        run_cmd(f"mysql -e \"FLUSH PRIVILEGES;\"")

        # Test DB connection
        code, _ = run_cmd(f"mysql -u{db_user} -p'{db_pass}' -e 'SELECT 1;' {db_name}")
        if code == 0:
            _log("   ✅ База данных создана")
        else:
            _log("   ❌ Ошибка подключения к БД")

        # Step 6: Download Chamilo
        _log(f"📥 Скачивание Chamilo {chamilo_ver}...")
        _state["progress"] = 40
        run_cmd(f"rm -rf /var/www/html/chamilo /tmp/chamilo-lms-{chamilo_ver}.zip")
        code, _ = run_cmd(
            f"wget -q -O /tmp/chamilo-lms-{chamilo_ver}.zip "
            f"'https://github.com/chamilo/chamilo-lms/releases/download/v{chamilo_ver}/chamilo-{chamilo_ver}.zip' "
            f"|| wget -q -O /tmp/chamilo-lms-{chamilo_ver}.zip "
            f"'https://github.com/chamilo/chamilo-lms/archive/refs/tags/v{chamilo_ver}.zip'"
        )
        if code != 0:
            _log("   ❌ Ошибка скачивания. Проверьте версию Chamilo.")
            _state["status"] = "error"
            _state["installing"] = False
            ssh.close()
            return

        # Step 7: Extract
        run_cmd(
            f"cd /tmp && unzip -q -o chamilo-lms-{chamilo_ver}.zip",
            "Распаковка...", 55
        )
        run_cmd(
            f"EXTRACTED=$(ls -d /tmp/chamilo*/ 2>/dev/null | head -1) && "
            f"mv \"$EXTRACTED\" /var/www/html/chamilo",
            "", 60
        )
        run_cmd("chown -R www-data:www-data /var/www/html/chamilo")
        run_cmd("chmod -R 755 /var/www/html/chamilo")
        _log("   ✅ Chamilo распакован")

        # Step 8: Configure PHP
        run_cmd(
            f"sed -i 's/^upload_max_filesize.*/upload_max_filesize = 100M/' /etc/php/{php_short}/apache2/php.ini && "
            f"sed -i 's/^post_max_size.*/post_max_size = 120M/' /etc/php/{php_short}/apache2/php.ini && "
            f"sed -i 's/^;\\?session.cookie_httponly.*/session.cookie_httponly = On/' /etc/php/{php_short}/apache2/php.ini",
            "Настройка PHP...", 65
        )

        # Step 9: Create configuration.php
        _log("⚙️ Создание configuration.php...")
        _state["progress"] = 70

        config_content = f"""<?php
// Chamilo configuration file — auto-generated
$_configuration['root_web'] = 'http://' . $_SERVER['HTTP_HOST'] . '/chamilo/';
$_configuration['root_sys'] = '/var/www/html/chamilo/';
$_configuration['db_host'] = 'localhost';
$_configuration['db_port'] = '3306';
$_configuration['main_database'] = '{db_name}';
$_configuration['db_user'] = '{db_user}';
$_configuration['db_password'] = '{db_pass}';
$_configuration['db_manager_enabled'] = false;
$_configuration['software_name'] = 'Chamilo';
$_configuration['software_url'] = 'https://chamilo.org';
$_configuration['deny_delete_users'] = false;
$_configuration['system_version'] = '{chamilo_ver}';
$_configuration['system_stable'] = true;
$_configuration['security_key'] = md5(uniqid(rand(), true));
?>"""
        # Escape for bash
        config_escaped = config_content.replace("'", "'\\''")
        run_cmd(f"echo '{config_escaped}' > /var/www/html/chamilo/app/config/configuration.php")
        run_cmd("chown www-data:www-data /var/www/html/chamilo/app/config/configuration.php")
        _log("   ✅ configuration.php создан")

        # Step 10: Import DB schema via Chamilo CLI install
        _log("🗄️ Импорт схемы базы данных...")
        _state["progress"] = 75

        install_cmd = (
            f"cd /var/www/html/chamilo && "
            f"php main/install/install.cli.php "
            f"--dbhost=localhost --dbport=3306 "
            f"--dbname={db_name} --dbuser={db_user} --dbpass='{db_pass}' "
            f"--adminLastName=Admin --adminFirstName=Chamilo "
            f"--adminLogin={admin_login} --adminPassword='{admin_pass}' "
            f"--adminEmail={admin_email} "
            f"--language={platform_lang} "
            f"--siteName='Chamilo LMS' "
            f"--siteUrl='http://{host}/chamilo/' "
            f"--institution='My Organisation' "
            f"2>&1 | tail -20"
        )
        code, output = run_cmd(install_cmd)

        if code != 0:
            _log("   ⚠️ CLI install не сработал, пробуем через SQL-дамп...")
            # Fallback: try to find and import SQL
            run_cmd(
                f"SQLFILE=$(find /var/www/html/chamilo -name 'db_main.sql' -o -name 'migration*.sql' 2>/dev/null | head -1) && "
                f"[ -n \"$SQLFILE\" ] && mysql -u{db_user} -p'{db_pass}' {db_name} < \"$SQLFILE\" && echo 'SQL imported' || echo 'No SQL found'"
            )

        # Step 11: Fix permissions
        run_cmd(
            "chown -R www-data:www-data /var/www/html/chamilo && "
            "find /var/www/html/chamilo -type d -exec chmod 755 {} + && "
            "find /var/www/html/chamilo -type f -exec chmod 644 {} +",
            "Настройка прав доступа...", 85
        )

        # Step 12: Apache config
        _log("🌐 Настройка Apache...")
        _state["progress"] = 90

        apache_conf = """
<Directory /var/www/html/chamilo>
    Options FollowSymLinks
    AllowOverride All
    Require all granted
</Directory>
"""
        run_cmd(f"echo '{apache_conf}' > /etc/apache2/conf-available/chamilo.conf")
        run_cmd("a2enconf chamilo 2>/dev/null || true")
        run_cmd("a2enmod rewrite 2>/dev/null || true")
        run_cmd("systemctl restart apache2")

        # Step 13: Final check
        _log("🔍 Проверка установки...")
        _state["progress"] = 95
        code, output = run_cmd(f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost/chamilo/")
        if output.strip() in ["200", "302", "301"]:
            _log(f"   ✅ Chamilo доступен (HTTP {output.strip()})")
        else:
            _log(f"   ⚠️ HTTP {output.strip()} — возможно нужно завершить установку через браузер")

        ssh.close()

        _state["progress"] = 100
        _state["status"] = "done"
        _log("")
        _log("=" * 50)
        _log("✅ Установка завершена!")
        _log(f"   URL: http://{host}/chamilo/")
        _log(f"   Логин: {admin_login}")
        _log(f"   Пароль: {admin_pass}")
        _log("=" * 50)

    except Exception as e:
        _log(f"❌ Ошибка: {str(e)}")
        _state["status"] = "error"

    finally:
        _state["installing"] = False


# ═══════════════════════════════════════════
#  Run
# ═══════════════════════════════════════════

if __name__ == "__main__":
    mode = "desktop"
    if "--web" in sys.argv:
        mode = "web"

    print("=" * 50)
    print("🔧 Chamilo LMS Installer")
    print("=" * 50)

    if mode == "desktop":
        try:
            import webview

            server = threading.Thread(
                target=lambda: app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False),
                daemon=True
            )
            server.start()

            # Wait for server
            import urllib.request
            for _ in range(30):
                try:
                    urllib.request.urlopen("http://127.0.0.1:5001/")
                    break
                except Exception:
                    time.sleep(0.3)

            webview.create_window(
                title="Chamilo LMS — Installer",
                url="http://127.0.0.1:5001",
                width=1000,
                height=750,
                min_size=(800, 600),
                resizable=True,
                text_select=True,
            )
            webview.start()
        except ImportError:
            print("pywebview не установлен, запуск в режиме Web...")
            print("   http://localhost:5001")
            app.run(host="0.0.0.0", port=5001, debug=True)
    else:
        print("   http://localhost:5001")
        app.run(host="0.0.0.0", port=5001, debug=True)
