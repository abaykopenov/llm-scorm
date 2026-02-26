"""
Unit-тесты для llm_generator.py.

Проверяет:
- Валидацию JSON-структуры курса
- Генерацию промпта
- Загрузку из файла
"""

import json
import os
import sys
import tempfile
import unittest

# Добавляем путь к модулям
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm_generator import LLMCourseGenerator, VALID_BLOCK_TYPES


class TestValidateJSON(unittest.TestCase):
    """Тесты валидации JSON-структуры."""

    def test_valid_course(self):
        course = {
            "title": "Тест",
            "description": "Описание",
            "language": "ru",
            "pages": [
                {
                    "title": "Страница 1",
                    "blocks": [
                        {"type": "text", "title": "Блок", "body": "Текст"}
                    ]
                }
            ]
        }
        errors = LLMCourseGenerator.validate_course_json(course)
        self.assertEqual(errors, [])

    def test_missing_title(self):
        errors = LLMCourseGenerator.validate_course_json({"pages": []})
        self.assertTrue(any("title" in e for e in errors))

    def test_missing_pages(self):
        errors = LLMCourseGenerator.validate_course_json({"title": "Тест"})
        self.assertTrue(any("pages" in e for e in errors))

    def test_empty_pages(self):
        errors = LLMCourseGenerator.validate_course_json(
            {"title": "Тест", "pages": []}
        )
        self.assertTrue(any("пуст" in e for e in errors))

    def test_not_dict(self):
        errors = LLMCourseGenerator.validate_course_json("not a dict")
        self.assertTrue(len(errors) > 0)

    def test_pages_not_list(self):
        errors = LLMCourseGenerator.validate_course_json(
            {"title": "Тест", "pages": "not a list"}
        )
        self.assertTrue(any("массив" in e for e in errors))


class TestValidateMCQ(unittest.TestCase):
    """Тесты валидации MCQ-блоков."""

    def _make_course(self, blocks):
        return {
            "title": "Тест",
            "pages": [{"title": "P", "blocks": blocks}]
        }

    def test_valid_mcq(self):
        blocks = [{
            "type": "mcq", "title": "Q", "body": "?",
            "options": [
                {"text": "A", "correct": True},
                {"text": "B", "correct": False},
            ],
            "feedback_correct": "!", "feedback_incorrect": "!"
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertEqual(errors, [])

    def test_mcq_no_correct(self):
        blocks = [{
            "type": "mcq", "title": "Q", "body": "?",
            "options": [
                {"text": "A", "correct": False},
                {"text": "B", "correct": False},
            ]
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("правильный ответ" in e for e in errors))

    def test_mcq_multiple_correct(self):
        blocks = [{
            "type": "mcq", "title": "Q", "body": "?",
            "options": [
                {"text": "A", "correct": True},
                {"text": "B", "correct": True},
            ]
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("ровно 1" in e for e in errors))

    def test_mcq_too_few_options(self):
        blocks = [{
            "type": "mcq", "title": "Q", "body": "?",
            "options": [{"text": "A", "correct": True}]
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("минимум 2" in e for e in errors))


class TestValidateNewBlocks(unittest.TestCase):
    """Тесты валидации новых типов блоков."""

    def _make_course(self, blocks):
        return {
            "title": "Тест",
            "pages": [{"title": "P", "blocks": blocks}]
        }

    def test_valid_fillin(self):
        blocks = [{
            "type": "fillin", "title": "Q", "body": "___",
            "correct_answer": "ответ"
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertEqual(errors, [])

    def test_fillin_no_answer(self):
        blocks = [{"type": "fillin", "title": "Q", "body": "___"}]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("correct_answer" in e for e in errors))

    def test_valid_matching(self):
        blocks = [{
            "type": "matching", "title": "Q", "body": "Match",
            "pairs": [
                {"left": "A", "right": "1"},
                {"left": "B", "right": "2"},
            ]
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertEqual(errors, [])

    def test_matching_too_few_pairs(self):
        blocks = [{
            "type": "matching", "title": "Q", "body": "Match",
            "pairs": [{"left": "A", "right": "1"}]
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("минимум 2" in e for e in errors))

    def test_valid_ordering(self):
        blocks = [{
            "type": "ordering", "title": "Q", "body": "Sort",
            "items": ["A", "B", "C"]
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertEqual(errors, [])

    def test_ordering_too_few_items(self):
        blocks = [{
            "type": "ordering", "title": "Q", "body": "Sort",
            "items": ["A"]
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("минимум 2" in e for e in errors))

    def test_valid_truefalse(self):
        blocks = [{
            "type": "truefalse", "title": "Q", "body": "Stmt",
            "correct_answer": True
        }]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertEqual(errors, [])

    def test_truefalse_no_answer(self):
        blocks = [{"type": "truefalse", "title": "Q", "body": "Stmt"}]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("correct_answer" in e for e in errors))

    def test_unknown_block_type(self):
        blocks = [{"type": "foobar", "title": "Q", "body": "?"}]
        errors = LLMCourseGenerator.validate_course_json(self._make_course(blocks))
        self.assertTrue(any("foobar" in e for e in errors))


class TestValidBlockTypes(unittest.TestCase):
    """Тест списка допустимых типов блоков."""

    def test_all_expected_types(self):
        expected = {"text", "mcq", "truefalse", "fillin", "matching", "ordering"}
        self.assertEqual(VALID_BLOCK_TYPES, expected)


class TestBuildPrompt(unittest.TestCase):
    """Тесты генерации промпта."""

    def test_prompt_contains_topic(self):
        prompt = LLMCourseGenerator._build_prompt("Python", 3, "ru")
        self.assertIn("Python", prompt)

    def test_prompt_contains_language(self):
        prompt = LLMCourseGenerator._build_prompt("Test", 3, "ru")
        self.assertIn("русском", prompt)

        prompt_en = LLMCourseGenerator._build_prompt("Test", 3, "en")
        self.assertIn("английском", prompt_en)

    def test_prompt_contains_all_block_types(self):
        prompt = LLMCourseGenerator._build_prompt("Test", 3, "ru")
        for btype in ["text", "mcq", "truefalse", "fillin", "matching", "ordering"]:
            self.assertIn(f'"{btype}"', prompt)

    def test_prompt_contains_page_count(self):
        prompt = LLMCourseGenerator._build_prompt("Test", 5, "ru")
        self.assertIn("5", prompt)

    def test_extra_instructions(self):
        prompt = LLMCourseGenerator._build_prompt(
            "Test", 3, "ru", extra_instructions="Добавь примеры кода"
        )
        self.assertIn("Добавь примеры кода", prompt)


class TestGenerateFromFile(unittest.TestCase):
    """Тесты загрузки JSON из файла."""

    def test_load_valid_file(self):
        course = {
            "title": "Тест",
            "pages": [
                {"title": "P1", "blocks": [{"type": "text", "title": "T", "body": "B"}]}
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(course, f, ensure_ascii=False)
            tmp_path = f.name

        try:
            result = LLMCourseGenerator.generate_from_file(tmp_path)
            self.assertEqual(result["title"], "Тест")
            self.assertEqual(len(result["pages"]), 1)
        finally:
            os.unlink(tmp_path)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            LLMCourseGenerator.generate_from_file("/nonexistent/path.json")

    def test_file_missing_title(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"pages": []}, f)
            tmp_path = f.name

        try:
            with self.assertRaises(ValueError):
                LLMCourseGenerator.generate_from_file(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_file_missing_pages(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"title": "Test"}, f)
            tmp_path = f.name

        try:
            with self.assertRaises(ValueError):
                LLMCourseGenerator.generate_from_file(tmp_path)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
