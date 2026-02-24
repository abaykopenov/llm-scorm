"""
LLM → SCORM → Chamilo Pipeline — CLI.

Примеры использования:
    # Из готового JSON
    python main.py --input examples/sample_course.json

    # С указанием выходного файла
    python main.py --input examples/sample_course.json --output my_course.zip

    # Генерация через LLM (требуется OPENAI_API_KEY)
    python main.py --topic "Основы Python" --pages 5

    # Генерация на английском
    python main.py --topic "Machine Learning Basics" --pages 4 --lang en
"""

import argparse
import sys

from llm_generator import LLMCourseGenerator
from scorm_builder import SCORMBuilder


def main():
    # Fix Windows console encoding for emoji/unicode output
    import io
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="LLM → SCORM Pipeline: генерация SCORM 1.2 пакетов",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python main.py --input examples/sample_course.json
  python main.py --input data.json --output course.zip
  python main.py --topic "Основы SQL" --pages 4
  python main.py --topic "Docker basics" --pages 3 --lang en
        """,
    )

    # Input source (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--input", "-i",
        metavar="FILE",
        help="Путь к JSON-файлу с содержимым курса",
    )
    group.add_argument(
        "--topic", "-t",
        metavar="TOPIC",
        help="Тема курса для генерации через LLM",
    )

    # Optional arguments
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Путь для сохранения SCORM ZIP (по умолчанию: output/<название>.zip)",
    )
    parser.add_argument(
        "--pages", "-p",
        type=int,
        default=3,
        metavar="N",
        help="Количество страниц при генерации через LLM (по умолчанию: 3)",
    )
    parser.add_argument(
        "--lang", "-l",
        default="ru",
        choices=["ru", "en"],
        help="Язык курса (по умолчанию: ru)",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="OpenAI API ключ (или установите OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="Модель OpenAI (по умолчанию: gpt-4o-mini)",
    )

    args = parser.parse_args()

    generator = LLMCourseGenerator(
        api_key=args.api_key,
        model=args.model,
    )

    # ------------------------------------------------------------------
    # Получение JSON курса
    # ------------------------------------------------------------------
    print("=" * 50)
    print("🚀 LLM → SCORM Pipeline")
    print("=" * 50)

    if args.input:
        print(f"\n📂 Загрузка курса из: {args.input}")
        try:
            course = generator.generate_from_file(args.input)
        except (FileNotFoundError, ValueError) as e:
            print(f"\n❌ Ошибка: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"\n🤖 Генерация курса через LLM...")
        print(f"   Тема: {args.topic}")
        print(f"   Страниц: {args.pages}")
        print(f"   Язык: {args.lang}")
        try:
            course = generator.generate_course(
                topic=args.topic,
                num_pages=args.pages,
                language=args.lang,
            )
        except (ValueError, ImportError) as e:
            print(f"\n❌ Ошибка: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"\n📝 Курс: {course.get('title', 'Без названия')}")
    print(f"   Страниц: {len(course.get('pages', []))}")

    total_blocks = sum(len(p.get("blocks", [])) for p in course.get("pages", []))
    quiz_blocks = sum(
        1
        for p in course.get("pages", [])
        for b in p.get("blocks", [])
        if b.get("type") in ("mcq", "truefalse")
    )
    print(f"   Блоков: {total_blocks} (вопросов: {quiz_blocks})")

    # ------------------------------------------------------------------
    # Сборка SCORM
    # ------------------------------------------------------------------
    print(f"\n📦 Сборка SCORM 1.2 пакета...")

    builder = SCORMBuilder()
    try:
        output_path = builder.build(course, args.output)
    except Exception as e:
        print(f"\n❌ Ошибка сборки: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 50}")
    print(f"✅ Готово!")
    print(f"   Файл: {output_path}")
    print(f"\n📖 Для загрузки в Chamilo:")
    print(f"   Курс → Learning Path → Import SCORM → загрузить ZIP")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
