"""
Chamilo LMS Uploader — автоматическая загрузка SCORM-пакетов в Chamilo.

Использует веб-интерфейс Chamilo через HTTP-сессию:
1. Авторизация через форму логина
2. Создание Learning Path с импортом SCORM
"""

import os
import re

import config

try:
    import requests
except ImportError:
    requests = None


class ChamiloUploader:
    """Загрузчик SCORM-пакетов в Chamilo LMS."""

    def __init__(self, chamilo_url: str | None = None,
                 username: str | None = None,
                 password: str | None = None):
        self.chamilo_url = (chamilo_url or config.CHAMILO_URL).rstrip("/")
        self.username = username or config.CHAMILO_USER
        self.password = password or config.CHAMILO_PASSWORD
        self.session = None

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def upload(self, scorm_zip_path: str, course_code: str | None = None) -> bool:
        """Загрузка SCORM-пакета в Chamilo.

        Args:
            scorm_zip_path: Путь к ZIP-файлу SCORM.
            course_code: Код курса в Chamilo. Если не указан —
                         используется первый доступный курс.

        Returns:
            bool — True при успешной загрузке.
        """
        if requests is None:
            raise ImportError(
                "Пакет requests не установлен. Выполните: pip install requests"
            )

        if not self.chamilo_url:
            raise ValueError(
                "URL Chamilo не задан. Укажите --chamilo-url или "
                "установите CHAMILO_URL в .env файле."
            )

        if not self.password:
            raise ValueError(
                "Пароль Chamilo не задан. Укажите --chamilo-pass или "
                "установите CHAMILO_PASSWORD в .env файле."
            )

        if not os.path.isfile(scorm_zip_path):
            raise FileNotFoundError(f"SCORM-файл не найден: {scorm_zip_path}")

        print(f"🌐 Подключение к Chamilo: {self.chamilo_url}")

        # 1. Создаём сессию и логинимся
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "LLM-SCORM-Pipeline/1.0"
        })

        if not self._login():
            return False

        # 2. Получаем список курсов или используем указанный
        if not course_code:
            course_code = self._get_first_course()
            if not course_code:
                print("❌ Не найдено ни одного курса в Chamilo.")
                print("   Создайте курс вручную и укажите его код через --chamilo-course")
                return False

        print(f"📚 Курс: {course_code}")

        # 3. Загружаем SCORM
        success = self._upload_scorm(scorm_zip_path, course_code)

        if success:
            print(f"✅ SCORM загружен в Chamilo!")
            print(f"   Откройте: {self.chamilo_url}/courses/{course_code}/index.php")
        else:
            print("❌ Ошибка загрузки SCORM в Chamilo.")

        return success

    # ------------------------------------------------------------------
    # Авторизация
    # ------------------------------------------------------------------

    def _login(self) -> bool:
        """Авторизация в Chamilo через веб-форму."""
        print(f"🔐 Авторизация как: {self.username}")

        # Получаем страницу логина для CSRF token
        login_page_url = f"{self.chamilo_url}/index.php"
        try:
            resp = self.session.get(login_page_url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"❌ Не удалось подключиться к Chamilo: {e}")
            return False

        # Ищем CSRF/security token
        csrf_token = ""
        # Chamilo 1.11.x использует _token или sec_token
        token_match = re.search(
            r'name=["\'](?:_token|sec_token|csrf_token)["\']\s+value=["\']([^"\']+)["\']',
            resp.text
        )
        if token_match:
            csrf_token = token_match.group(1)

        # Отправляем форму логина
        login_data = {
            "login": self.username,
            "password": self.password,
            "submitAuth": "1",
        }
        if csrf_token:
            login_data["sec_token"] = csrf_token
            login_data["_token"] = csrf_token

        try:
            resp = self.session.post(
                login_page_url,
                data=login_data,
                timeout=15,
                allow_redirects=True,
            )
        except requests.RequestException as e:
            print(f"❌ Ошибка авторизации: {e}")
            return False

        # Проверяем успешность логина
        if "logout" in resp.text.lower() or "user_portal" in resp.url:
            print("✅ Авторизация успешна")
            return True

        # Альтернативная проверка
        if self.username.lower() in resp.text.lower():
            print("✅ Авторизация успешна")
            return True

        print("❌ Не удалось авторизоваться. Проверьте логин и пароль.")
        return False

    # ------------------------------------------------------------------
    # Список курсов
    # ------------------------------------------------------------------

    def _get_first_course(self) -> str | None:
        """Получение кода первого доступного курса."""
        try:
            resp = self.session.get(
                f"{self.chamilo_url}/user_portal.php",
                timeout=15,
            )
            # Ищем ссылки на курсы: /courses/CODE/
            matches = re.findall(
                r'/courses/([A-Z0-9_]+)/index\.php',
                resp.text,
                re.IGNORECASE,
            )
            if matches:
                return matches[0]
        except requests.RequestException:
            pass

        # Альтернативный поиск через main/
        try:
            resp = self.session.get(
                f"{self.chamilo_url}/main/auth/courses.php",
                timeout=15,
            )
            matches = re.findall(
                r'course_code=([A-Z0-9_]+)',
                resp.text,
                re.IGNORECASE,
            )
            if matches:
                return matches[0]
        except requests.RequestException:
            pass

        return None

    # ------------------------------------------------------------------
    # Загрузка SCORM
    # ------------------------------------------------------------------

    def _upload_scorm(self, scorm_zip_path: str, course_code: str) -> bool:
        """Загрузка SCORM-пакета в Learning Path курса."""

        # URL страницы импорта SCORM
        # Chamilo 1.11.x: /main/lp/lp_controller.php?action=import&cidReq=CODE
        import_url = (
            f"{self.chamilo_url}/main/lp/lp_controller.php"
            f"?cidReq={course_code}&action=import_scorm"
        )

        print(f"📤 Загрузка файла: {os.path.basename(scorm_zip_path)}")

        # Получаем страницу импорта (для токенов)
        try:
            resp = self.session.get(import_url, timeout=15)
        except requests.RequestException as e:
            print(f"❌ Ошибка доступа к странице импорта: {e}")
            return False

        # Ищем токен на странице импорта
        token = ""
        token_match = re.search(
            r'name=["\'](?:_token|sec_token)["\']\s+value=["\']([^"\']+)["\']',
            resp.text
        )
        if token_match:
            token = token_match.group(1)

        # Загружаем файл
        filename = os.path.basename(scorm_zip_path)
        try:
            with open(scorm_zip_path, "rb") as f:
                files = {
                    "user_file": (filename, f, "application/zip"),
                }
                data = {
                    "submit": "Upload",
                }
                if token:
                    data["sec_token"] = token
                    data["_token"] = token

                resp = self.session.post(
                    import_url,
                    files=files,
                    data=data,
                    timeout=60,
                    allow_redirects=True,
                )
        except requests.RequestException as e:
            print(f"❌ Ошибка загрузки: {e}")
            return False

        # Проверяем успешность
        if resp.status_code == 200:
            # Ищем признаки успешной загрузки
            if ("lp_controller.php" in resp.url and "action=import" not in resp.url):
                return True
            if "success" in resp.text.lower() or "imported" in resp.text.lower():
                return True
            # Если нет явной ошибки — считаем успехом
            if "error" not in resp.text.lower()[:500]:
                return True

        return False
