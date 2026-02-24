"""
LLM → SCORM → Chamilo Pipeline — CLI.

Примеры использования:
    # Из готового JSON
    python main.py --input examples/sample_course.json

    # Генерация через локальную модель + автозагрузка в Chamilo
    python main.py --topic "Docker" --base-url http://192.168.1.100:11434/v1 --model llama3 --upload

    # Все настройки в .env файле — просто задаёте тему:
    python main.py --topic "Основы SQL"
    python main.py --topic "Кибербезопасность" --upload
"""

import argparse
import sys

from llm_generator import LLMCourseGenerator
from scorm_builder import SCORMBuilder


def main():
    # Fix Windows console encoding for emoji/unicode output
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="LLM → SCORM → Chamilo Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Из готового JSON
  python main.py --input examples/sample_course.json

  # Генерация курса по теме (настройки LLM из .env)
  python main.py --topic "Основы Python"

  # Генерация + автозагрузка в Chamilo
  python main.py --topic "Docker" --upload

  # Указать LLM-сервер вручную
  python main.py --topic "SQL" --base-url http://192.168.1.100:11434/v1 --model llama3

  # Полный пайплайн с ручными параметрами
  python main.py --topic "Git" --base-url http://192.168.1.100:11434/v1 --model llama3 \\
      --upload --chamilo-url http://192.168.1.50/chamilo --chamilo-user admin --chamilo-pass secret

Совет: создайте .env файл из .env.example, тогда достаточно:
  python main.py --topic "Любая тема" --upload
        """,
    )

    # ---- Источник контента ----
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--input", "-i",
        metavar="FILE",
        help="Путь к JSON-файлу с содержимым курса",
    )
    group.add_argument(
        "--topic", "-t",
        metavar="ТЕМА",
        help="Тема курса — ИИ сгенерирует контент автоматически",
    )

    # ---- LLM параметры ----
    llm_group = parser.add_argument_group("LLM (генерация контента)")
    llm_group.add_argument(
        "--base-url",
        metavar="URL",
        help="URL сервера LLM (напр.: http://192.168.1.100:11434/v1)",
    )
    llm_group.add_argument(
        "--model",
        metavar="MODEL",
        help="Модель LLM (llama3, mistral, gpt-4o-mini...)",
    )
    llm_group.add_argument(
        "--api-key",
        metavar="KEY",
        help="OpenAI API ключ (для облачных моделей)",
    )
    llm_group.add_argument(
        "--pages", "-p",
        type=int,
        default=3,
        metavar="N",
        help="Количество страниц (по умолчанию: 3)",
    )
    llm_group.add_argument(
        "--lang", "-l",
        default="ru",
        choices=["ru", "en"],
        help="Язык курса (по умолчанию: ru)",
    )

    # ---- SCORM параметры ----
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Путь для сохранения SCORM ZIP",
    )

    # ---- Chamilo параметры ----
    chamilo_group = parser.add_argument_group("Chamilo LMS (автозагрузка)")
    chamilo_group.add_argument(
        "--upload",
        action="store_true",
        help="Автоматически загрузить SCORM в Chamilo после сборки",
    )
    chamilo_group.add_argument(
        "--chamilo-url",
        metavar="URL",
        help="URL Chamilo (напр.: http://192.168.1.50/chamilo)",
    )
    chamilo_group.add_argument(
        "--chamilo-user",
        metavar="USER",
        help="Логин администратора Chamilo (по умолчанию: admin)",
    )
    chamilo_group.add_argument(
        "--chamilo-pass",
        metavar="PASS",
        help="Пароль администратора Chamilo",
    )
    chamilo_group.add_argument(
        "--chamilo-course",
        metavar="CODE",
        help="Код курса в Chamilo (если не указан — первый доступный)",
    )

    args = parser.parse_args()

    # ==================================================================
    # ШАГ 1: Получение JSON курса
    # ==================================================================
    print("=" * 55)
    print("🚀 LLM → SCORM → Chamilo Pipeline")
    print("=" * 55)

    generator = LLMCourseGenerator(
        api_key=args.api_key,
        model=args.model,
        base_url=getattr(args, 'base_url', None),
    )

    if args.input:
        print(f"\n📂 ШАГ 1: Загрузка курса из файла")
        print(f"   Файл: {args.input}")
        try:
            course = generator.generate_from_file(args.input)
        except (FileNotFoundError, ValueError) as e:
            print(f"\n❌ Ошибка: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"\n🤖 ШАГ 1: Генерация курса через ИИ")
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
        except Exception as e:
            err_msg = str(e)
            if "insufficient_quota" in err_msg or "429" in err_msg:
                print(f"\n❌ Квота OpenAI исчерпана.", file=sys.stderr)
                print("   Проверьте баланс: https://platform.openai.com/account/billing", file=sys.stderr)
            elif "401" in err_msg or "invalid_api_key" in err_msg:
                print(f"\n❌ Неверный API ключ.", file=sys.stderr)
            elif "Connection" in err_msg or "connect" in err_msg.lower():
                print(f"\n❌ Не удалось подключиться к LLM-серверу.", file=sys.stderr)
                print(f"   Проверьте что сервер запущен и доступен.", file=sys.stderr)
            else:
                print(f"\n❌ Ошибка LLM: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"\n   ✅ Курс: {course.get('title', 'Без названия')}")
    print(f"      Страниц: {len(course.get('pages', []))}")

    total_blocks = sum(len(p.get("blocks", [])) for p in course.get("pages", []))
    quiz_blocks = sum(
        1
        for p in course.get("pages", [])
        for b in p.get("blocks", [])
        if b.get("type") in ("mcq", "truefalse")
    )
    print(f"      Блоков: {total_blocks} (вопросов: {quiz_blocks})")

    # ==================================================================
    # ШАГ 2: Сборка SCORM
    # ==================================================================
    print(f"\n📦 ШАГ 2: Сборка SCORM 1.2 пакета...")

    builder = SCORMBuilder()
    try:
        output_path = builder.build(course, args.output)
    except Exception as e:
        print(f"\n❌ Ошибка сборки: {e}", file=sys.stderr)
        sys.exit(1)

    # ==================================================================
    # ШАГ 3: Загрузка в Chamilo (если --upload)
    # ==================================================================
    if args.upload:
        print(f"\n🌐 ШАГ 3: Загрузка в Chamilo LMS...")

        from chamilo_uploader import ChamiloUploader

        uploader = ChamiloUploader(
            chamilo_url=getattr(args, 'chamilo_url', None),
            username=getattr(args, 'chamilo_user', None),
            password=getattr(args, 'chamilo_pass', None),
        )

        try:
            success = uploader.upload(
                scorm_zip_path=output_path,
                course_code=getattr(args, 'chamilo_course', None),
            )
            if not success:
                print("\n⚠️  Автозагрузка не удалась. Загрузите вручную:")
                print(f"   Файл: {output_path}")
                print(f"   Chamilo → Курс → Learning Path → Import SCORM")
        except (ValueError, ImportError) as e:
            print(f"\n❌ {e}", file=sys.stderr)
            print(f"   Файл всё равно создан: {output_path}")
        except Exception as e:
            print(f"\n❌ Ошибка загрузки в Chamilo: {e}", file=sys.stderr)
            print(f"   Файл всё равно создан: {output_path}")
    else:
        print(f"\n💡 Добавьте --upload для автозагрузки в Chamilo")

    # ==================================================================
    # Итог
    # ==================================================================
    print(f"\n{'=' * 55}")
    print(f"✅ Готово!")
    print(f"   SCORM: {output_path}")
    if not args.upload:
        print(f"\n   Для загрузки в Chamilo вручную:")
        print(f"   Курс → Learning Path → Import SCORM → загрузить ZIP")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
