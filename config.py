"""
Конфигурация проекта LLM → SCORM → Chamilo Pipeline.

Для работы с OpenAI API установите переменную окружения OPENAI_API_KEY
или передайте ключ напрямую в LLMCourseGenerator.

Для локальных моделей (Ollama, LM Studio, vLLM) установите OPENAI_BASE_URL
на адрес вашего сервера, например: http://192.168.1.100:11434/v1
"""

import logging
import os

logger = logging.getLogger(__name__)

# Загрузка .env файла (если есть)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv не установлен — используем только переменные окружения

# ==============================
# LLM Configuration
# ==============================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")  # Для локальных моделей
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

# ==============================
# Chamilo LMS Configuration
# ==============================
CHAMILO_URL = os.getenv("CHAMILO_URL", "")           # http://192.168.1.50/chamilo
CHAMILO_USER = os.getenv("CHAMILO_USER", "admin")
CHAMILO_PASSWORD = os.getenv("CHAMILO_PASSWORD", "")
CHAMILO_API_KEY = os.getenv("CHAMILO_API_KEY", "")


# ==============================
# Thread-safe config reload (#3)
# ==============================
def get_config() -> dict:
    """Потокобезопасное перечитывание конфигурации из .env.

    Вместо importlib.reload(config) каждый вызов создаёт
    новый dict с актуальными значениями из .env файла.
    """
    try:
        from dotenv import load_dotenv as _load
        _load(override=True)
    except ImportError:
        pass

    return {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "OPENAI_TEMPERATURE": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
        "OPENAI_MAX_TOKENS": int(os.getenv("OPENAI_MAX_TOKENS", "4096")),
        "CHAMILO_URL": os.getenv("CHAMILO_URL", ""),
        "CHAMILO_USER": os.getenv("CHAMILO_USER", "admin"),
        "CHAMILO_PASSWORD": os.getenv("CHAMILO_PASSWORD", ""),
        "CHAMILO_API_KEY": os.getenv("CHAMILO_API_KEY", ""),
    }
