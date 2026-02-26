"""
LLM Course Generator — многошаговая генерация иерархичного SCORM-курса.

Поддерживает типы блоков:
- text       — текстовый блок с теорией
- mcq        — вопрос с вариантами ответа
- truefalse  — верно / неверно
- fillin     — заполни пропуск
- matching   — сопоставление (пары)
- ordering   — сортировка (расположи по порядку)
"""

import json
import logging
import os
import time
from typing import Callable, Any

import config

logger = logging.getLogger(__name__)

VALID_BLOCK_TYPES = {"text", "mcq", "truefalse", "fillin", "matching", "ordering"}
VALID_DETAIL_LEVELS = {"brief", "normal", "detailed", "expert"}

class LLMCourseGenerator:
    """Оркестратор генерации SCORM-курса (Каркас -> SCO -> SCO -> Тест)."""

    MAX_RETRIES = 3
    RETRY_DELAY = 3

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.base_url = base_url or config.OPENAI_BASE_URL or None
        self.model = model or config.OPENAI_MODEL
        logger.info("LLMCourseGenerator: model=%s, base_url=%s",
                     self.model, self.base_url or "OpenAI API")

    # ------------------------------------------------------------------
    # Оркестратор
    # ------------------------------------------------------------------

    def generate_course(self, topic: str, language: str = "ru",
                        num_modules: int = 1, sections_per_module: int = 1,
                        scos_per_section: int = 1, screens_per_sco: int = 2,
                        questions_per_sco: int = 1, final_test_questions: int = 5,
                        detail_level: str = "normal",
                        temperature: float | None = None,
                        max_tokens: int | None = None,
                        progress_callback: Callable[[str, int], None] | None = None) -> dict:
        """
        Многошаговая генерация курса.
        
        Args:
            topic: Тема курса
            ...
            progress_callback: Функция f(message: str, percent: int) для UI.
        """
        if not self.api_key and not self.base_url:
            raise ValueError("LLM API key или Base URL не задан.")

        temp = temperature if temperature is not None else config.OPENAI_TEMPERATURE
        tokens = max_tokens or config.OPENAI_MAX_TOKENS

        def report(msg: str, pct: int):
            logger.info("Прогресс [%d%%]: %s", pct, msg)
            if progress_callback:
                progress_callback(msg, pct)

        total_scos = num_modules * sections_per_module * scos_per_section
        scos_completed = 0

        # ----------------------------------------------------
        # Шаг 1: Генерация Каркаса (Outline)
        # ----------------------------------------------------
        report("Генерация структуры курса...", 5)
        outline_prompt = self._build_outline_prompt(
            topic, language, num_modules, sections_per_module, scos_per_section
        )
        
        course = self._call_llm(
            prompt=outline_prompt, temp=temp, tokens=tokens,
            sys_prompt="Ты эксперт по методологии (педагогический дизайнер). Верни только JSON."
        )

        # Добавим настройки (временно хардкодим дефолты или можно передавать)
        course["settings"] = {
            "passing_score": 80,
            "max_attempts": 3,
            "max_time_minutes": 60
        }
        course["language"] = language

        # ----------------------------------------------------
        # Шаг 2: Генерация Контента каждого SCO
        # ----------------------------------------------------
        report("Генерация контента уроков...", 15)
        
        # Индексы прогресса: от 15% до 85%
        for mod in course.get("modules", []):
            for sec in mod.get("sections", []):
                for sco in sec.get("scos", []):
                    sco_title = sco.get("title", "Untitled SCO")
                    pct = 15 + int(((scos_completed) / total_scos) * 70)
                    report(f"Генерация контента: {sco_title}", pct)

                    sco_prompt = self._build_sco_prompt(
                        topic=topic,
                        course_outline=json.dumps(course, ensure_ascii=False),
                        target_sco_title=sco_title,
                        language=language,
                        screens_per_sco=screens_per_sco,
                        questions_per_sco=questions_per_sco,
                        detail_level=detail_level
                    )

                    sco_data = self._call_llm(
                        prompt=sco_prompt, temp=temp, tokens=tokens,
                        sys_prompt="Ты автор учебных материалов. Верни JSON со структурой экранов и вопросов."
                    )
                    
                    # Подмешиваем сгенерированные экраны и вопросы
                    sco["screens"] = sco_data.get("screens", [])
                    sco["knowledge_check"] = sco_data.get("knowledge_check", [])
                    scos_completed += 1

        # ----------------------------------------------------
        # Шаг 3: Генерация Итогового Теста
        # ----------------------------------------------------
        if final_test_questions > 0:
            report("Генерация итогового теста...", 90)
            test_prompt = self._build_test_prompt(
                topic, json.dumps(course, ensure_ascii=False), language, final_test_questions
            )
            test_data = self._call_llm(
                prompt=test_prompt, temp=temp, tokens=tokens,
                sys_prompt="Ты экзаменатор. Верни JSON с массивом вопросов для финального теста."
            )
            course["final_test"] = test_data.get("final_test", [])
        else:
            course["final_test"] = []

        # ----------------------------------------------------
        # Завершение
        # ----------------------------------------------------
        report("Курс успешно сгенерирован!", 100)
        
        # Валидация
        errors = self.validate_course_json(course)
        if errors:
            logger.warning("Валидация итогового JSON выявила проблемы: %s", errors)

        return course

    # ------------------------------------------------------------------
    # LLM Wrapper
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str, temp: float, tokens: int, sys_prompt: str) -> dict:
        """Вспомогательный метод с retry-логикой для вызова LLM и парсинга JSON."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("Пакет openai не установлен.")

        client_kwargs = {"api_key": self.api_key or "local"}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = OpenAI(**client_kwargs)

        request_kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temp,
            "max_tokens": tokens,
        }

        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                try:
                    request_kwargs["response_format"] = {"type": "json_object"}
                    response = client.chat.completions.create(**request_kwargs)
                except Exception:
                    # Fallback для моделей, не поддерживающих json_object
                    if "response_format" in request_kwargs:
                        del request_kwargs["response_format"]
                    response = client.chat.completions.create(**request_kwargs)

                raw = response.choices[0].message.content.strip()
                
                # Cleanup markdown
                if raw.startswith("```"):
                    lines = raw.split("\n")
                    if lines[0].startswith("```"): lines = lines[1:]
                    if lines and lines[-1].strip() == "```": lines = lines[:-1]
                    raw = "\n".join(lines)

                return json.loads(raw)

            except json.JSONDecodeError as e:
                last_error = e
                logger.warning("JSONDecodeError попытка %d: %s", attempt, str(e))
                if attempt < self.MAX_RETRIES: time.sleep(self.RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error("LLM Error попытка %d: %s", attempt, str(e))
                if attempt < self.MAX_RETRIES: time.sleep(self.RETRY_DELAY)

        raise RuntimeError(f"Сбой вызова LLM после {self.MAX_RETRIES} попыток: {last_error}")

    # ------------------------------------------------------------------
    # Промпты
    # ------------------------------------------------------------------

    def _build_outline_prompt(self, topic: str, language: str,
                              num_modules: int, sections: int, scos: int) -> str:
        lang_label = "русском" if language == "ru" else "английском"
        return f"""Создай структуру учебного курса на тему "{topic}" на {lang_label} языке.
Структура должна состоять из:
- {num_modules} Модуль(ей)
- В каждом модуле {sections} Раздел(а)
- В каждом разделе {scos} Урок(ов) (SCO)

Верни ТОЛЬКО JSON:
{{
  "title": "Название курса",
  "description": "Краткое описание курса",
  "modules": [
    {{
      "title": "Название модуля",
      "sections": [
        {{
          "title": "Название раздела",
          "scos": [
            {{ "title": "Название урока" }}
          ]
        }}
      ]
    }}
  ]
}}"""

    def _build_sco_prompt(self, topic: str, course_outline: str, target_sco_title: str,
                          language: str, screens_per_sco: int, questions_per_sco: int,
                          detail_level: str) -> str:
        lang_label = "русском" if language == "ru" else "английском"
        
        detail_map = {
            "brief": "Каждый экран: 2-3 предложения главного.",
            "normal": "Каждый экран: 1-2 абзаца + примеры.",
            "detailed": "Каждый экран: 2-3 абзаца, глубоко.",
            "expert": "Каждый экран: 3-5 абзацев, технически глубоко."
        }
        detail_text = detail_map.get(detail_level, detail_map["normal"])

        return f"""Мы создаем курс "{topic}". 
Вот его общая структура (для контекста):
{course_outline}

Твоя задача — написать детальный контент только для урока: "{target_sco_title}" на {lang_label} языке.

Требования:
- {screens_per_sco} экранов теории (каждый экран - один text-блок).
- {detail_text}
- {questions_per_sco} вопросов(а) для проверки знаний после теории (в массиве knowledge_check).

Типы вопросов: mcq, truefalse, fillin, matching, ordering.

Верни ТОЛЬКО JSON:
{{
  "screens": [
    {{
      "title": "Название экрана",
      "blocks": [
        {{
          "type": "text",
          "title": "Заголовок",
          "body": "<p>HTML-текст</p>"
        }}
      ]
    }}
  ],
  "knowledge_check": [
    {{
      "type": "mcq",
      "title": "Вопрос",
      "body": "Текст",
      "options": [{{"text":"Да","correct":true}}, {{"text":"Нет","correct":false}}],
      "feedback_correct": "...",
      "feedback_incorrect": "..."
    }}
  ]
}}"""

    def _build_test_prompt(self, topic: str, course_db: str, language: str, limit: int) -> str:
        lang_label = "русском" if language == "ru" else "английском"
        return f"""Мы завершили курс "{topic}" на {lang_label} языке.
Сгенерируй Итоговый тест из {limit} сложных вопросов, покрывающий весь материал.
Типы вопросов: mcq, truefalse, fillin, matching, ordering. (Используй разные).

Верни ТОЛЬКО JSON:
{{
  "final_test": [
    {{
       "type": "mcq",
       // ... поля вопроса
    }}
  ]
}}"""

    # ------------------------------------------------------------------
    # Валидация / Вспомогательные
    # ------------------------------------------------------------------

    @staticmethod
    def validate_course_json(data: dict) -> list[str]:
        """Рекурсивная валидация новой иерархичной структуры JSON."""
        errors = []
        if not isinstance(data, dict):
            return ["Корневой элемент должен быть объектом (dict)"]
        if "title" not in data: errors.append("Отсутствует 'title'")
        if "modules" not in data: 
            errors.append("Отсутствует 'modules'")
            return errors

        for i, mod in enumerate(data["modules"]):
            if "title" not in mod: errors.append(f"modules[{i}]: нет 'title'")
            if "sections" not in mod: errors.append(f"modules[{i}]: нет 'sections'")
            else:
                for j, sec in enumerate(mod["sections"]):
                    if "scos" not in sec: errors.append(f"modules[{i}].sections[{j}]: нет 'scos'")
                    else:
                        for k, sco in enumerate(sec["scos"]):
                            if "screens" not in sco:
                                errors.append(f"modules[{i}].sec[{j}].sco[{k}]: нет 'screens'")

        return errors

    @staticmethod
    def generate_from_file(path: str) -> dict:
        """Загрузка готовой JSON-структуры курса из файла."""
        if not os.path.isfile(path): raise FileNotFoundError(f"Файл не найден: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Для обратной совместимости старых файлов (course -> pages)
        # преобразуем плоский список pages в один модуль -> раздел -> SCOs
        if "pages" in data and "modules" not in data:
            logger.info("Конвертация старой схемы (pages) в новую (modules)...")
            scos = []
            for i, p in enumerate(data.get("pages", [])):
                # Все text блоки на один экран, вопросы в knowledge_check
                texts = [b for b in p.get("blocks", []) if b.get("type") == "text"]
                questions = [b for b in p.get("blocks", []) if b.get("type") != "text"]
                scos.append({
                    "title": p.get("title", f"Урок {i+1}"),
                    "screens": [{"title": "Введение", "blocks": texts}],
                    "knowledge_check": questions
                })
            
            data["modules"] = [{
                "title": "Основной модуль",
                "sections": [{
                    "title": "Раздел 1",
                    "scos": scos
                }]
            }]
            data["final_test"] = []
            del data["pages"]

        errors = LLMCourseGenerator.validate_course_json(data)
        if errors:
            logger.warning("Валидация файла %s: %s", path, "; ".join(errors))
            
        return data
