"""
Конфигурация проекта LLM → SCORM → Chamilo Pipeline.

Для работы с OpenAI API установите переменную окружения OPENAI_API_KEY
или передайте ключ напрямую в LLMCourseGenerator.
"""

import os

# ==============================
# LLM Configuration
# ==============================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4096"))

# ==============================
# SCORM Configuration
# ==============================
SCORM_VERSION = "1.2"
SCORM_SCHEMA_VERSION = "1.2"
SCORM_DEFAULT_ORG = "default-org"
SCORM_MASTERY_SCORE = 80  # Проходной балл (%)

# ==============================
# Course Defaults
# ==============================
DEFAULT_COURSE_LANGUAGE = "ru"
DEFAULT_NUM_PAGES = 3

# ==============================
# Paths
# ==============================
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")
