"""
SCORM 1.2 Builder — генерация иерархичного SCORM-пакета из JSON-структуры.

Создаёт ZIP-архив, содержащий:
- imsmanifest.xml  — манифест SCORM 1.2 с вложенными item (Модуль -> Раздел -> SCO)
- sco_X.html       — HTML-файлы для каждого SCO
- style.css        — стили
- scorm_api.js     — JS-обёртка SCORM API
"""

import logging
import os
import zipfile
import xml.etree.ElementTree as ET
from xml.dom import minidom

from jinja2 import Environment, FileSystemLoader

import config

logger = logging.getLogger(__name__)


class SCORMBuilder:
    """Генератор SCORM 1.2 пакетов с поддержкой иерархии."""

    def __init__(self, templates_dir: str | None = None):
        self.templates_dir = templates_dir or config.TEMPLATES_DIR
        self.env = Environment(
            loader=FileSystemLoader(self.templates_dir),
            autoescape=False,
        )
        logger.info("SCORMBuilder инициализирован: templates=%s", self.templates_dir)

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def build(self, course: dict, output_path: str | None = None) -> str:
        """Сборка SCORM-пакета.

        Args:
            course: JSON-структура курса (из LLMCourseGenerator).
            output_path: Путь для сохранения ZIP.
        """
        # Валидация входных данных
        self._validate_course(course)

        title = course.get("title", "Untitled Course")
        slug = self._slugify(title)
        logger.info("Сборка SCORM-пакета: '%s' (slug: %s)", title, slug)

        if not output_path:
            os.makedirs(config.OUTPUT_DIR, exist_ok=True)
            output_path = os.path.join(config.OUTPUT_DIR, f"{slug}.zip")

        # Чтение статических файлов
        style_css = self._read_template_file("style.css")
        scorm_js = self._read_template_file("scorm_api.js")

        files = {
            "style.css": style_css,
            "scorm_api.js": scorm_js,
        }

        # Генерация HTML-файлов для каждого SCO и Теста
        sco_index = 0
        resources = []  # Для манифеста
        organizations_tree = []  # Структура для манифеста

        for m_idx, mod in enumerate(course.get("modules", [])):
            mod_data = {"title": mod.get("title", f"Модуль {m_idx+1}"), "sections": []}
            for s_idx, sec in enumerate(mod.get("sections", [])):
                sec_data = {"title": sec.get("title", f"Раздел {s_idx+1}"), "scos": []}
                for u_idx, sco in enumerate(sec.get("scos", [])):
                    sco_index += 1
                    filename = f"sco_{m_idx}_{s_idx}_{u_idx}.html"
                    identifier = f"ITEM_{sco_index}"
                    res_id = f"RES_{sco_index}"

                    html = self._render_sco_html(course, sco, filename)
                    files[filename] = html

                    sec_data["scos"].append({
                        "id": identifier,
                        "res_id": res_id,
                        "title": sco.get("title", f"Урок {sco_index}"),
                    })
                    resources.append({"res_id": res_id, "href": filename})
                mod_data["sections"].append(sec_data)
            organizations_tree.append(mod_data)

        final_test = course.get("final_test", [])
        if final_test:
            sco_index += 1
            filename = "final_test.html"
            identifier = f"ITEM_{sco_index}"
            res_id = f"RES_{sco_index}"

            test_sco = {"title": "Итоговое тестирование", "knowledge_check": final_test, "screens": []}
            html = self._render_sco_html(course, test_sco, filename)
            files[filename] = html
            
            organizations_tree.append({
                "title": "Итоговое тестирование",
                "is_final": True,
                "id": identifier,
                "res_id": res_id
            })
            resources.append({"res_id": res_id, "href": filename})

        logger.debug("Генерация imsmanifest.xml...")
        manifest_xml = self._generate_manifest(course, organizations_tree, resources)
        files["imsmanifest.xml"] = manifest_xml

        # Упаковка в ZIP
        self._create_zip(files, output_path)

        try:
            print(f"[OK] SCORM package created: {output_path}")
        except UnicodeEncodeError:
            print(f"[OK] SCORM package: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_course(course: dict) -> None:
        if not isinstance(course, dict):
            raise ValueError("Курс должен быть словарём (dict)")
        if "title" not in course:
            raise ValueError("Курс должен содержать поле 'title'")
        if "modules" not in course:
            raise ValueError("Курс должен содержать массив 'modules'")

    # ------------------------------------------------------------------
    # Генерация HTML
    # ------------------------------------------------------------------

    def _render_sco_html(self, course: dict, sco: dict, filename: str) -> str:
        template = self.env.get_template("sco.html") # Нужно будет создать этот шаблон
        settings = course.get("settings", {})
        return template.render(
            course_title=course.get("title", "Untitled Course"),
            language=course.get("language", config.DEFAULT_COURSE_LANGUAGE),
            sco_title=sco.get("title", "Untitled SCO"),
            screens=sco.get("screens", []),
            knowledge_check=sco.get("knowledge_check", []),
            passing_score=settings.get("passing_score", config.SCORM_MASTERY_SCORE),
            scorm_version=config.SCORM_VERSION
        )

    # ------------------------------------------------------------------
    # Генерация imsmanifest.xml
    # ------------------------------------------------------------------

    def _generate_manifest(self, course: dict, org_tree: list, resources: list) -> str:
        title = course.get("title", "Untitled Course")
        identifier = self._slugify(title)

        nsmap = {
            "": "http://www.imsproject.org/xsd/imscp_rootv1p1p2",
            "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }

        manifest = ET.Element("manifest")
        manifest.set("identifier", identifier)
        manifest.set("version", "1.0")
        manifest.set("xmlns", nsmap[""])
        manifest.set("xmlns:adlcp", nsmap["adlcp"])
        manifest.set("xmlns:xsi", nsmap["xsi"])
        manifest.set(
            "xsi:schemaLocation",
            "http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd "
            "http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd",
        )

        # Metadata
        metadata = ET.SubElement(manifest, "metadata")
        schema = ET.SubElement(metadata, "schema")
        schema.text = "ADL SCORM"
        schema_ver = ET.SubElement(metadata, "schemaversion")
        schema_ver.text = config.SCORM_SCHEMA_VERSION

        # Organizations
        organizations = ET.SubElement(manifest, "organizations")
        organizations.set("default", config.SCORM_DEFAULT_ORG)

        org = ET.SubElement(organizations, "organization")
        org.set("identifier", config.SCORM_DEFAULT_ORG)

        org_title = ET.SubElement(org, "title")
        org_title.text = title

        settings = course.get("settings", {})
        mastery_val = str(settings.get("passing_score", config.SCORM_MASTERY_SCORE))

        # Build Organization Tree
        for m_idx, mod in enumerate(org_tree):
            if mod.get("is_final"):
                # Итоговый тест - как отдельный элемент корня
                item = ET.SubElement(org, "item")
                item.set("identifier", mod["id"])
                item.set("identifierref", mod["res_id"])
                item.set("isvisible", "true")
                t = ET.SubElement(item, "title")
                t.text = mod["title"]
                mastery = ET.SubElement(item, "adlcp:masteryscore")
                mastery.text = mastery_val
                continue

            # Модуль
            mod_item = ET.SubElement(org, "item")
            mod_item.set("identifier", f"MOD_{m_idx}")
            mod_item.set("isvisible", "true")
            mod_t = ET.SubElement(mod_item, "title")
            mod_t.text = mod["title"]

            for s_idx, sec in enumerate(mod.get("sections", [])):
                # Раздел
                sec_item = ET.SubElement(mod_item, "item")
                sec_item.set("identifier", f"MOD_{m_idx}_SEC_{s_idx}")
                sec_item.set("isvisible", "true")
                sec_t = ET.SubElement(sec_item, "title")
                sec_t.text = sec["title"]

                for sco in sec.get("scos", []):
                    # SCO
                    sco_item = ET.SubElement(sec_item, "item")
                    sco_item.set("identifier", sco["id"])
                    sco_item.set("identifierref", sco["res_id"])
                    sco_item.set("isvisible", "true")
                    sco_t = ET.SubElement(sco_item, "title")
                    sco_t.text = sco["title"]
                    # Для каждого SCO задаем passing score
                    mastery_el = ET.SubElement(sco_item, "adlcp:masteryscore")
                    mastery_el.text = mastery_val

        # Resources
        res_el = ET.SubElement(manifest, "resources")
        for res in resources:
            resource = ET.SubElement(res_el, "resource")
            resource.set("identifier", res["res_id"])
            resource.set("type", "webcontent")
            resource.set("adlcp:scormtype", "sco")
            resource.set("href", res["href"])

            f = ET.SubElement(resource, "file")
            f.set("href", res["href"])
            
            # Common dependencies
            for common_f in ["style.css", "scorm_api.js"]:
                f_dep = ET.SubElement(resource, "file")
                f_dep.set("href", common_f)

        rough = ET.tostring(manifest, encoding="unicode")
        dom = minidom.parseString(rough)
        pretty = dom.toprettyxml(indent="  ")

        lines = pretty.split("\n")
        if lines[0].startswith("<?xml"):
            lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
        else:
            lines.insert(0, '<?xml version="1.0" encoding="UTF-8"?>')
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _read_template_file(self, filename: str) -> str:
        path = os.path.join(self.templates_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _create_zip(files: dict[str, str], output_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        logger.debug("ZIP создан: %s (%d файлов)", output_path, len(files))

    @staticmethod
    def _slugify(text: str) -> str:
        translit = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
            "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k",
            "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
            "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
            "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",
            "ь": "", "э": "e", "ю": "yu", "я": "ya",
        }
        result = [translit.get(c, c) if c.isascii() and (c.isalnum() or c in "-_") or c.isascii() is False else "-" if c in " \t" else "" for c in text.lower()]
        slug = "".join(result).replace("--", "-").strip("-")
        return slug or "course"
