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

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.model = model or config.OPENAI_MODEL

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def generate_course(self, topic: str, num_pages: int | None = None,
                        language: str | None = None) -> dict:
        """Генерация курса через OpenAI API.

        Args:
            topic: Тема курса.
            num_pages: Количество страниц (по умолчанию из config).
            language: Язык курса (по умолчанию из config).

        Returns:
            dict — JSON-структура курса.
        """
        if not self.api_key:
            raise ValueError(
                "OpenAI API key не задан. Установите переменную окружения "
                "OPENAI_API_KEY или передайте ключ в конструктор."
            )

        num_pages = num_pages or config.DEFAULT_NUM_PAGES
        language = language or config.DEFAULT_COURSE_LANGUAGE

        prompt = self._build_prompt(topic, num_pages, language)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты — генератор учебных курсов. "
                            "Генерируй только валидный JSON без комментариев и markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=config.OPENAI_TEMPERATURE,
                max_tokens=config.OPENAI_MAX_TOKENS,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
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
    def _build_prompt(topic: str, num_pages: int, language: str) -> str:
        """Формирование промпта для LLM."""

        lang_label = "русском" if language == "ru" else "английском"

        return f"""Создай учебный курс на тему "{topic}" на {lang_label} языке.

Курс должен содержать ровно {num_pages} страниц.
Каждая страница должна содержать 2-4 блока.
Блоки могут быть трёх типов: "text", "mcq" (вопрос с вариантами), "truefalse".

Каждая страница должна содержать хотя бы один текстовый блок с теорией
и хотя бы один вопрос (mcq или truefalse).

Для MCQ вопросов: 3-5 вариантов ответа, ровно один correct: true.

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
