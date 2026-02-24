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

import json
import os

import config


class LLMCourseGenerator:
    """Генератор JSON-структуры курса."""

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.base_url = base_url or config.OPENAI_BASE_URL or None
        self.model = model or config.OPENAI_MODEL

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
            from openai import OpenAI

            # Настройка клиента: OpenAI API или локальная модель
            client_kwargs = {}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
                # Для локальных моделей API key может быть любым
                client_kwargs["api_key"] = self.api_key or "local"
                print(f"   Сервер: {self.base_url}")
            else:
                client_kwargs["api_key"] = self.api_key

            client = OpenAI(**client_kwargs)

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

            # json_object mode поддерживается не всеми моделями
            # (Ollama, vLLM обычно поддерживают, но некоторые — нет)
            try:
                request_kwargs["response_format"] = {"type": "json_object"}
                response = client.chat.completions.create(**request_kwargs)
            except Exception:
                # Fallback: без response_format
                del request_kwargs["response_format"]
                response = client.chat.completions.create(**request_kwargs)

            raw = response.choices[0].message.content

            # Очистка ответа от возможного markdown обрамления
            raw = raw.strip()
            if raw.startswith("```"):
                # Убираем ```json ... ```
                lines = raw.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw = "\n".join(lines)

            return json.loads(raw)

        except ImportError:
            raise ImportError(
                "Пакет openai не установлен. Выполните: pip install openai"
            )

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
    # Приватные методы
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
