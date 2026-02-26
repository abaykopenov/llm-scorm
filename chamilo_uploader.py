"""
Chamilo LMS Uploader — автоматическая загрузка SCORM-пакетов в Chamilo.

Использует веб-интерфейс Chamilo через HTTP-сессию:
1. Авторизация через форму логина
2. Создание Learning Path с импортом SCORM
"""

import logging
import os
import re

import config

logger = logging.getLogger(__name__)

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

        logger.info("🌐 Подключение к Chamilo: %s", self.chamilo_url)

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
                logger.error("❌ Не найдено ни одного курса в Chamilo.")
                logger.error("   Создайте курс вручную и укажите его код через --chamilo-course")
                return False

        logger.info("📚 Курс: %s", course_code)

        # 3. Загружаем SCORM
        success = self._upload_scorm(scorm_zip_path, course_code)

        if success:
            logger.info("✅ SCORM загружен в Chamilo!")
            logger.info("   Откройте: %s/courses/%s/index.php", self.chamilo_url, course_code)
        else:
            logger.error("❌ Ошибка загрузки SCORM в Chamilo.")

        return success

    # ------------------------------------------------------------------
    # Авторизация
    # ------------------------------------------------------------------

    def _login(self) -> bool:
        """Авторизация в Chamilo через веб-форму."""
        logger.info("🔐 Авторизация как: %s", self.username)

        # Получаем страницу логина для CSRF token
        login_page_url = f"{self.chamilo_url}/index.php"
        try:
            resp = self.session.get(login_page_url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("❌ Не удалось подключиться к Chamilo: %s", e)
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
            logger.info("✅ Авторизация успешна")
            return True

        # Альтернативная проверка
        if self.username.lower() in resp.text.lower():
            logger.info("✅ Авторизация успешна")
            return True

        logger.error("❌ Не удалось авторизоваться. Проверьте логин и пароль.")
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

        # Chamilo 1.11.x: SCORM upload через /main/upload/upload.php
        # Сначала открываем страницу формы для получения токенов
        form_url = (
            f"{self.chamilo_url}/main/upload/index.php"
            f"?cidReq={course_code}&id_session=0&gidReq=0"
            f"&gradebook=0&origin=&curdirpath=/&tool=learnpath"
        )

        logger.info("📤 Загрузка файла: %s", os.path.basename(scorm_zip_path))

        try:
            resp = self.session.get(form_url, timeout=15)
        except requests.RequestException as e:
            logger.error("❌ Ошибка доступа к странице импорта: %s", e)
            return False

        # Ищем action формы (URL куда отправлять)
        action_match = re.search(
            r'<form[^>]*action=["\']([^"\']*upload\.php[^"\']*)["\']',
            resp.text, re.IGNORECASE
        )
        if action_match:
            import html as html_mod
            upload_url = html_mod.unescape(action_match.group(1))
            # Если URL относительный — делаем абсолютным
            if upload_url.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(self.chamilo_url)
                upload_url = f"{parsed.scheme}://{parsed.netloc}{upload_url}"
            elif not upload_url.startswith("http"):
                upload_url = f"{self.chamilo_url}/main/upload/{upload_url}"
        else:
            # Fallback URL
            upload_url = (
                f"{self.chamilo_url}/main/upload/upload.php"
                f"?cidReq={course_code}&id_session=0&gidReq=0"
                f"&gradebook=0&origin="
            )

        logger.debug("   URL: %s", upload_url)

        # Ищем скрытые поля формы
        hidden_fields = {}
        for m in re.finditer(
            r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
            resp.text, re.IGNORECASE
        ):
            hidden_fields[m.group(1)] = m.group(2)

        # Также ищем в обратном порядке (value перед name)
        for m in re.finditer(
            r'<input[^>]*value=["\']([^"\']*)["\'][^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\']',
            resp.text, re.IGNORECASE
        ):
            hidden_fields[m.group(2)] = m.group(1)

        logger.debug("   Форма: %s", list(hidden_fields.keys()))

        # Загружаем файл
        filename = os.path.basename(scorm_zip_path)
        file_size = os.path.getsize(scorm_zip_path)

        try:
            with open(scorm_zip_path, "rb") as f:
                files = {
                    "user_file": (filename, f, "application/zip"),
                }
                data = {
                    "submit": "Upload",
                    "use_max_score": "1",
                    "curdirpath": "/",
                    "tool": "learnpath",
                    "MAX_FILE_SIZE": str(max(file_size * 2, 100000000)),
                }
                # Добавляем скрытые поля
                data.update(hidden_fields)

                resp = self.session.post(
                    upload_url,
                    files=files,
                    data=data,
                    timeout=120,
                    allow_redirects=True,
                )
        except requests.RequestException as e:
            logger.error("❌ Ошибка загрузки: %s", e)
            return False

        logger.debug("   HTTP %s, URL: %s", resp.status_code, resp.url)

        # Проверяем результат
        text_lower = resp.text.lower()

        # Признаки успеха: Chamilo редиректит на lp_controller или показывает LP
        if resp.status_code in (200, 302):
            # Успешный импорт: в ответе есть информация о новом LP
            if "lp_controller.php" in resp.url:
                logger.info("   ✅ Редирект на Learning Path — загрузка успешна")
                return True
            if "scorm" in text_lower and ("success" in text_lower or "import" in text_lower):
                return True
            # Если на странице есть ссылка на только что загруженный LP
            if re.search(r'lp_controller\.php.*action=view', resp.text):
                return True

            # Проверяем наличие ошибок
            error_patterns = [
                "error", "not allowed", "permission denied",
                "invalid file", "ошибка", "не удалось",
            ]
            has_error = any(p in text_lower[:2000] for p in error_patterns)

            if not has_error and resp.status_code == 200:
                # Вероятно успех — страница загрузилась без ошибок
                logger.info("   ✅ Страница без ошибок — загрузка вероятно успешна")
                return True

        logger.error("   ❌ Неожиданный ответ (HTTP %s)", resp.status_code)
        # Save debug info
        debug_path = os.path.join(os.path.dirname(__file__), "_upload_debug.html")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(resp.text)
        logger.debug("   Ответ сохранён: %s", debug_path)
        return False

