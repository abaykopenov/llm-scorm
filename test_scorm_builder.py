"""
Unit-тесты для scorm_builder.py.

Проверяет:
- Валидацию входных данных курса
- Генерацию imsmanifest.xml
- Сборку SCORM-пакета (ZIP)
- Slugify / транслитерацию
"""

import os
import sys
import tempfile
import zipfile
import unittest

# Добавляем путь к модулям
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scorm_builder import SCORMBuilder


class TestSCORMBuilderSlugify(unittest.TestCase):
    """Тесты транслитерации и slugify."""

    def test_russian_text(self):
        self.assertEqual(SCORMBuilder._slugify("Основы Python"), "osnovy-python")

    def test_english_text(self):
        self.assertEqual(SCORMBuilder._slugify("Machine Learning Basics"), "machine-learning-basics")

    def test_mixed_text(self):
        result = SCORMBuilder._slugify("Курс по Docker 101")
        self.assertTrue(result)
        self.assertNotIn(" ", result)

    def test_empty_string(self):
        self.assertEqual(SCORMBuilder._slugify(""), "course")

    def test_special_characters(self):
        result = SCORMBuilder._slugify("Тест!@#$%^&*()")
        self.assertTrue(len(result) > 0)

    def test_multiple_hyphens(self):
        result = SCORMBuilder._slugify("a   b   c")
        self.assertNotIn("--", result)


class TestSCORMBuilderValidation(unittest.TestCase):
    """Тесты валидации входных данных."""

    def test_valid_course(self):
        course = {
            "title": "Тестовый курс",
            "pages": [
                {
                    "title": "Страница 1",
                    "blocks": [
                        {"type": "text", "title": "Блок", "body": "Текст"}
                    ]
                }
            ]
        }
        # Не должен выбросить исключение
        SCORMBuilder._validate_course(course)

    def test_missing_title(self):
        with self.assertRaises(ValueError):
            SCORMBuilder._validate_course({"pages": []})

    def test_missing_pages(self):
        with self.assertRaises(ValueError):
            SCORMBuilder._validate_course({"title": "Тест"})

    def test_pages_not_list(self):
        with self.assertRaises(ValueError):
            SCORMBuilder._validate_course({"title": "Тест", "pages": "not a list"})

    def test_not_dict(self):
        with self.assertRaises(ValueError):
            SCORMBuilder._validate_course("not a dict")

    def test_empty_pages(self):
        # Должен пройти (warning, но не exception)
        SCORMBuilder._validate_course({"title": "Тест", "pages": []})

    def test_page_without_blocks(self):
        # Должен пройти (warning)
        SCORMBuilder._validate_course({
            "title": "Тест",
            "pages": [{"title": "P1"}]
        })


class TestSCORMBuilderBuild(unittest.TestCase):
    """Тесты сборки SCORM-пакета."""

    def setUp(self):
        self.builder = SCORMBuilder()
        self.sample_course = {
            "title": "Тестовый курс",
            "description": "Описание курса",
            "language": "ru",
            "pages": [
                {
                    "title": "Введение",
                    "blocks": [
                        {
                            "type": "text",
                            "title": "Что такое тест",
                            "body": "<p>Это тестовый блок.</p>"
                        },
                        {
                            "type": "mcq",
                            "title": "Вопрос 1",
                            "body": "Что верно?",
                            "options": [
                                {"text": "Да", "correct": True},
                                {"text": "Нет", "correct": False}
                            ],
                            "feedback_correct": "Верно!",
                            "feedback_incorrect": "Неверно."
                        }
                    ]
                }
            ]
        }

    def test_build_creates_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_course.zip")
            result = self.builder.build(self.sample_course, output_path)

            self.assertEqual(result, output_path)
            self.assertTrue(os.path.isfile(output_path))

    def test_zip_contains_required_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_course.zip")
            self.builder.build(self.sample_course, output_path)

            with zipfile.ZipFile(output_path) as zf:
                names = zf.namelist()
                self.assertIn("imsmanifest.xml", names)
                self.assertIn("index.html", names)
                self.assertIn("style.css", names)
                self.assertIn("scorm_api.js", names)

    def test_manifest_is_valid_xml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_course.zip")
            self.builder.build(self.sample_course, output_path)

            with zipfile.ZipFile(output_path) as zf:
                manifest = zf.read("imsmanifest.xml").decode("utf-8")
                self.assertIn('<?xml version="1.0"', manifest)
                self.assertIn("ADL SCORM", manifest)
                self.assertIn("imscp_rootv1p1p2", manifest)

    def test_html_contains_course_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_course.zip")
            self.builder.build(self.sample_course, output_path)

            with zipfile.ZipFile(output_path) as zf:
                html = zf.read("index.html").decode("utf-8")
                self.assertIn("Тестовый курс", html)
                self.assertIn("Введение", html)
                self.assertIn("Это тестовый блок", html)

    def test_build_with_new_block_types(self):
        """Тест сборки с новыми типами блоков (fillin, matching, ordering)."""
        course = {
            "title": "Курс с новыми блоками",
            "language": "ru",
            "pages": [
                {
                    "title": "Страница",
                    "blocks": [
                        {
                            "type": "fillin",
                            "title": "Заполни пропуск",
                            "body": "Столица России — _____",
                            "correct_answer": "Москва",
                            "accept_alternatives": ["москва"],
                            "feedback_correct": "Верно!",
                            "feedback_incorrect": "Неверно."
                        },
                        {
                            "type": "matching",
                            "title": "Сопоставь",
                            "body": "Соедини",
                            "pairs": [
                                {"left": "A", "right": "1"},
                                {"left": "B", "right": "2"}
                            ],
                            "feedback_correct": "Верно!",
                            "feedback_incorrect": "Неверно."
                        },
                        {
                            "type": "ordering",
                            "title": "Расположи",
                            "body": "По порядку",
                            "items": ["Один", "Два", "Три"],
                            "feedback_correct": "Верно!",
                            "feedback_incorrect": "Неверно."
                        }
                    ]
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "new_blocks.zip")
            result = self.builder.build(course, output_path)
            self.assertTrue(os.path.isfile(result))

            with zipfile.ZipFile(output_path) as zf:
                html = zf.read("index.html").decode("utf-8")
                self.assertIn("fillin-input", html)
                self.assertIn("matching-container", html)
                self.assertIn("ordering-list", html)


class TestSCORMBuilderManifest(unittest.TestCase):
    """Тесты генерации imsmanifest.xml."""

    def setUp(self):
        self.builder = SCORMBuilder()

    def test_manifest_structure(self):
        course = {"title": "Test", "description": "Desc", "pages": []}
        xml = self.builder._generate_manifest(course)

        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', xml)
        self.assertIn('<manifest', xml)
        self.assertIn('<metadata>', xml)
        self.assertIn('<organizations', xml)
        self.assertIn('<resources>', xml)
        self.assertIn('adlcp:masteryscore', xml)


if __name__ == "__main__":
    unittest.main()
