"""
LLM Course Generator — генерация JSON-структуры курса через OpenAI API.

Поддерживает два режима:
1. Генерация через LLM (OpenAI API) — по теме
2. Загрузка готового JSON — из файла

Промежуточный формат JSON:
{
    "title": "Название курса",
    "description": "Описание курса",
    "language": "ru",
    "pages": [
        {
            "title": "Название страницы",
            "blocks": [
                {
                    "type": "text",
                    "title": "Заголовок блока",
                    "body": "Текст блока (HTML)"
                },
                {
                    "type": "mcq",
                    "title": "Вопрос",
                    "body": "Текст вопроса",
                    "options": [
                        {"text": "Вариант 1", "correct": true},
                        {"text": "Вариант 2", "correct": false}
                    ],
                    "feedback_correct": "Правильно!",
                    "feedback_incorrect": "Неправильно."
                },
                {
                    "type": "truefalse",
                    "title": "Вопрос True/False",
                    "body": "Утверждение",
                    "correct_answer": true,
                    "feedback_correct": "Верно!",
                    "feedback_incorrect": "Неверно."
                }
            ]
        }
    ]
}
"""

import hashlib
import json
import logging
import os
import re
import time

import config

logger = logging.getLogger(__name__)


class LLMCourseGenerator:
    """Генератор JSON-структуры курса."""

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.base_url = base_url or config.OPENAI_BASE_URL or None
        self.model = model or config.OPENAI_MODEL

        # Lazy client (#8)
        self._client = None
        # Cached flag for json_object support (#7)
        self._supports_json_format = None

    # ------------------------------------------------------------------
    # Lazy OpenAI client (#8)
    # ------------------------------------------------------------------

    @property
    def client(self):
        """Ленивая инициализация OpenAI клиента — переиспользуется."""
        if self._client is None:
            from openai import OpenAI

            kwargs = {}
            if self.base_url:
                kwargs["base_url"] = self.base_url
                kwargs["api_key"] = self.api_key or "local"
                logger.info("LLM server: %s", self.base_url)
            else:
                kwargs["api_key"] = self.api_key

            self._client = OpenAI(**kwargs)
        return self._client

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def generate_course(self, topic: str, num_pages: int | None = None,
                        language: str | None = None,
                        temperature: float | None = None,
                        max_tokens: int | None = None,
                        blocks_per_page: int = 3,
                        questions_per_page: int = 1,
                        detail_level: str = "normal",
                        system_prompt: str | None = None,
                        extra_instructions: str | None = None) -> dict:
        """Генерация курса через OpenAI API.

        Args:
            topic: Тема курса.
            num_pages: Количество страниц (по умолчанию из config).
            language: Язык курса (по умолчанию из config).
            temperature: Температура генерации (0.0-1.5).
            max_tokens: Максимальное количество токенов.
            blocks_per_page: Блоков на страницу (2-5).
            questions_per_page: Вопросов на страницу (1-3).
            detail_level: Уровень детальности (brief/normal/detailed/expert).
            system_prompt: Кастомный системный промпт.
            extra_instructions: Дополнительные инструкции.

        Returns:
            dict — JSON-структура курса.
        """
        # Для локальных моделей API key не обязателен
        if not self.api_key and not self.base_url:
            raise ValueError(
                "OpenAI API key не задан. Установите переменную окружения "
                "OPENAI_API_KEY или передайте ключ в конструктор.\n"
                "Для локальных моделей укажите --base-url (API key не нужен)."
            )

        num_pages = num_pages or config.DEFAULT_NUM_PAGES
        language = language or config.DEFAULT_COURSE_LANGUAGE
        temperature = temperature if temperature is not None else config.OPENAI_TEMPERATURE
        max_tokens = max_tokens or config.OPENAI_MAX_TOKENS

        prompt = self._build_prompt(
            topic, num_pages, language,
            blocks_per_page=blocks_per_page,
            questions_per_page=questions_per_page,
            detail_level=detail_level,
            extra_instructions=extra_instructions,
        )

        try:
            # Системный промпт
            sys_prompt = system_prompt or (
                "Ты — генератор учебных курсов. "
                "Генерируй только валидный JSON без комментариев и markdown."
            )

            # Параметры запроса
            request_kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            # json_object mode — с кэшированием флага (#7)
            if self._supports_json_format is None:
                # Первый вызов: пробуем с json_object
                try:
                    request_kwargs["response_format"] = {"type": "json_object"}
                    response = self._call_llm_with_retry(request_kwargs)
                    self._supports_json_format = True
                except Exception:
                    # Fallback: запоминаем что не поддерживается
                    self._supports_json_format = False
                    del request_kwargs["response_format"]
                    response = self._call_llm_with_retry(request_kwargs)
            elif self._supports_json_format:
                request_kwargs["response_format"] = {"type": "json_object"}
                response = self._call_llm_with_retry(request_kwargs)
            else:
                response = self._call_llm_with_retry(request_kwargs)

            raw = response.choices[0].message.content
            return self._parse_llm_response(raw)

        except ImportError:
            raise ImportError(
                "Пакет openai не установлен. Выполните: pip install openai"
            )

    def generate_course_cached(self, topic: str, num_pages: int | None = None,
                               language: str | None = None, **kwargs) -> dict:
        """Генерация курса с кэшированием (#6).

        Если курс с такими же параметрами уже генерировался,
        возвращает результат из кэша.
        """
        num_pages = num_pages or config.DEFAULT_NUM_PAGES
        language = language or config.DEFAULT_COURSE_LANGUAGE

        key = self._cache_key(topic, num_pages, language, **kwargs)
        cache_path = os.path.join(config.OUTPUT_DIR, f"cache_{key}.json")

        if os.path.isfile(cache_path):
            logger.info("Using cached course: %s", cache_path)
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)

        course = self.generate_course(
            topic=topic, num_pages=num_pages, language=language, **kwargs
        )

        # Save to cache
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(course, f, ensure_ascii=False, indent=2)
        logger.info("Course cached: %s", cache_path)

        return course

    @staticmethod
    def generate_from_file(path: str) -> dict:
        """Загрузка готовой JSON-структуры курса из файла.

        Args:
            path: Путь к JSON-файлу.

        Returns:
            dict — JSON-структура курса.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Файл не найден: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Базовая валидация
        if "title" not in data:
            raise ValueError("JSON должен содержать поле 'title'")
        if "pages" not in data or not isinstance(data["pages"], list):
            raise ValueError("JSON должен содержать массив 'pages'")

        return data

    # ------------------------------------------------------------------
    # Retry logic (#13)
    # ------------------------------------------------------------------

    def _call_llm_with_retry(self, request_kwargs: dict,
                             max_retries: int = 3) -> object:
        """Вызов LLM с retry и exponential backoff (#13)."""
        for attempt in range(max_retries):
            try:
                return self.client.chat.completions.create(**request_kwargs)
            except Exception as e:
                err_str = str(e)
                is_retryable = (
                    isinstance(e, (ConnectionError, TimeoutError))
                    or "429" in err_str
                    or "500" in err_str
                    or "502" in err_str
                    or "503" in err_str
                    or "connect" in err_str.lower()
                    or "timeout" in err_str.lower()
                )
                if is_retryable and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "LLM attempt %d/%d failed: %s. Retrying in %ds...",
                        attempt + 1, max_retries, e, wait
                    )
                    time.sleep(wait)
                else:
                    raise

    # ------------------------------------------------------------------
    # JSON parsing (#14)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_llm_response(raw: str) -> dict:
        """Надёжный парсинг JSON-ответа от LLM (#14).

        Обрабатывает: markdown обрамление, trailing commas,
        вложенный JSON, валидация структуры.
        """
        raw = raw.strip()

        # Убираем markdown обрамление
        raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
        raw = re.sub(r'\n?```\s*$', '', raw)

        # Убираем trailing commas (частая ошибка LLM)
        raw = re.sub(r',\s*([}\]])', r'\1', raw)

        # Пробуем JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Ищем первый { и последний }
            start = raw.find('{')
            end = raw.rfind('}') + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(raw[start:end])
                except json.JSONDecodeError:
                    logger.error("Failed to parse LLM response: %s...", raw[:200])
                    raise ValueError(
                        "LLM вернул невалидный JSON. Попробуйте повторить генерацию."
                    )
            else:
                logger.error("No JSON found in LLM response: %s...", raw[:200])
                raise ValueError(
                    "LLM не вернул JSON-ответ. Попробуйте повторить генерацию."
                )

        # Валидация структуры
        if "title" not in data:
            raise ValueError("LLM не вернул поле 'title'")
        if "pages" not in data or not isinstance(data["pages"], list):
            raise ValueError("LLM не вернул массив 'pages'")

        return data

    # ------------------------------------------------------------------
    # Cache key (#6)
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(topic: str, num_pages: int, language: str, **kwargs) -> str:
        """Генерация ключа кэша для курса."""
        sig = f"{topic}:{num_pages}:{language}:{json.dumps(kwargs, sort_keys=True)}"
        return hashlib.md5(sig.encode()).hexdigest()[:12]

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(topic: str, num_pages: int, language: str,
                      blocks_per_page: int = 3, questions_per_page: int = 1,
                      detail_level: str = "normal",
                      extra_instructions: str | None = None) -> str:
        """Формирование промпта для LLM."""

        lang_label = "русском" if language == "ru" else "английском"

        # Детальность
        detail_map = {
            "brief": "Каждый текстовый блок — 2-3 предложения, только самое важное.",
            "normal": "Каждый текстовый блок — 1-2 абзаца с теорией и примерами.",
            "detailed": "Каждый текстовый блок — 2-3 абзаца с подробными объяснениями, примерами и определениями.",
            "expert": "Каждый текстовый блок — 3-5 абзацев с углублённым анализом, примерами кода, таблицами и ссылками.",
        }
        detail_text = detail_map.get(detail_level, detail_map["normal"])

        text_blocks = blocks_per_page - questions_per_page
        if text_blocks < 1:
            text_blocks = 1

        extra = ""
        if extra_instructions:
            extra = f"\n\nДополнительные требования:\n{extra_instructions}"

        return f"""Создай учебный курс на тему "{topic}" на {lang_label} языке.

Курс должен содержать ровно {num_pages} страниц.
Каждая страница должна содержать {text_blocks} текстовых блок(ов) с теорией
и {questions_per_page} вопрос(ов) (mcq или truefalse).
Итого {blocks_per_page} блоков на каждой странице.

{detail_text}

Блоки могут быть трёх типов: "text", "mcq" (вопрос с вариантами), "truefalse".
Для MCQ вопросов: 3-5 вариантов ответа, ровно один correct: true.{extra}

Верни JSON в следующем формате:
{{
    "title": "Название курса",
    "description": "Краткое описание курса (1-2 предложения)",
    "language": "{language}",
    "pages": [
        {{
            "title": "Название страницы",
            "blocks": [
                {{
                    "type": "text",
                    "title": "Заголовок",
                    "body": "<p>HTML-текст теории. Можно использовать <strong>, <em>, <ul>, <li>, <code>.</p>"
                }},
                {{
                    "type": "mcq",
                    "title": "Вопрос",
                    "body": "Текст вопроса",
                    "options": [
                        {{"text": "Вариант 1", "correct": true}},
                        {{"text": "Вариант 2", "correct": false}},
                        {{"text": "Вариант 3", "correct": false}}
                    ],
                    "feedback_correct": "Правильно! Потому что...",
                    "feedback_incorrect": "Неправильно. Правильный ответ: ..."
                }},
                {{
                    "type": "truefalse",
                    "title": "Верно или неверно",
                    "body": "Утверждение для проверки",
                    "correct_answer": true,
                    "feedback_correct": "Верно!",
                    "feedback_incorrect": "Неверно. На самом деле..."
                }}
            ]
        }}
    ]
}}

Верни ТОЛЬКО JSON, без пояснений и markdown."""

    # ------------------------------------------------------------------
    # Slugify (#9 — optimized)
    # ------------------------------------------------------------------

    @staticmethod
    def _slugify(text: str) -> str:
        """Простая транслитерация и slugify для идентификаторов."""
        translit = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
            "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k",
            "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
            "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
            "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",
            "ь": "", "э": "e", "ю": "yu", "я": "ya",
        }
        result = []
        for char in text.lower():
            if char in translit:
                result.append(translit[char])
            elif char.isascii() and (char.isalnum() or char in "-_"):
                result.append(char)
            elif char in " \t":
                result.append("-")
        slug = "".join(result)
        # Collapse multiple hyphens (#9 — re.sub instead of while loop)
        slug = re.sub(r'-{2,}', '-', slug)
        return slug.strip("-") or "course"
