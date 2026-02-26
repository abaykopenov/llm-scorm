"""
SCORM 1.2 Builder — генерация SCORM-пакета из JSON-структуры курса.

Создаёт ZIP-архив, содержащий:
- imsmanifest.xml  — манифест SCORM 1.2
- index.html       — HTML-страница курса (из Jinja2 шаблона)
- style.css        — стили
- scorm_api.js     — JS-обёртка SCORM API
"""

import logging
import os
import re
import zipfile
import xml.etree.ElementTree as ET

from jinja2 import Environment, FileSystemLoader

import config

logger = logging.getLogger(__name__)

# Jinja2 Environment cache (#11)
_env_cache: dict[str, Environment] = {}


class SCORMBuilder:
    """Генератор SCORM 1.2 пакетов."""

    def __init__(self, templates_dir: str | None = None):
        self.templates_dir = templates_dir or config.TEMPLATES_DIR

        # Cache Environment per templates_dir (#11)
        if self.templates_dir not in _env_cache:
            _env_cache[self.templates_dir] = Environment(
                loader=FileSystemLoader(self.templates_dir),
                autoescape=False,
            )
        self.env = _env_cache[self.templates_dir]

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def build(self, course: dict, output_path: str | None = None) -> str:
        """Сборка SCORM-пакета.

        Args:
            course: JSON-структура курса (из LLMCourseGenerator).
            output_path: Путь для сохранения ZIP. Если не задан —
                         используется output/<slug>.zip.

        Returns:
            str — путь к созданному ZIP-файлу.
        """
        title = course.get("title", "Untitled Course")
        slug = self._slugify(title)

        if not output_path:
            os.makedirs(config.OUTPUT_DIR, exist_ok=True)
            output_path = os.path.join(config.OUTPUT_DIR, f"{slug}.zip")

        manifest_xml = self._generate_manifest(course)

        # Чтение статических файлов
        style_css = self._read_template_file("style.css")
        scorm_js = self._read_template_file("scorm_api.js")

        # Упаковка в ZIP
        files = {
            "imsmanifest.xml": manifest_xml,
            "style.css": style_css,
            "scorm_api.js": scorm_js,
        }
        
        # Добавляем страницы (Multi-SCO)
        pages = course.get("pages", [])
        if not pages:
            # Fallback для пустого курса
            files["index.html"] = self._render_html(course)
        else:
            for page_idx, page in enumerate(pages):
                html_content = self._render_page_html(course, page, page_idx)
                files[f"page_{page_idx + 1}.html"] = html_content
                
            # Сохраняем и общий index.html на случай, если кто-то запустит напрямую
            files["index.html"] = self._render_html(course)

        self._create_zip(files, output_path)

        logger.info("SCORM package created: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Генерация imsmanifest.xml (#10 — ET.indent instead of minidom)
    # ------------------------------------------------------------------

    def _generate_manifest(self, course: dict) -> str:
        """Генерация SCORM 1.2 imsmanifest.xml."""

        title = course.get("title", "Untitled Course")
        description = course.get("description", "")
        identifier = self._slugify(title)

        # Namespace map
        nsmap = {
            "": "http://www.imsproject.org/xsd/imscp_rootv1p1p2",
            "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }

        # Build XML manually for proper namespace handling
        manifest = ET.Element("manifest")
        manifest.set("identifier", identifier)
        manifest.set("version", "1.0")
        manifest.set("xmlns", nsmap[""])
        manifest.set("xmlns:adlcp", nsmap["adlcp"])
        manifest.set("xmlns:xsi", nsmap["xsi"])
        manifest.set(
            "xsi:schemaLocation",
            "http://www.imsproject.org/xsd/imscp_rootv1p1p2 "
            "imscp_rootv1p1p2.xsd "
            "http://www.adlnet.org/xsd/adlcp_rootv1p2 "
            "adlcp_rootv1p2.xsd",
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

        # Pages (Multi-SCO)
        pages = course.get("pages", [])
        if not pages:
            # Empty course fallback
            item = ET.SubElement(org, "item")
            item.set("identifier", "item-1")
            item.set("identifierref", "resource-1")
            item.set("isvisible", "true")
            
            item_title = ET.SubElement(item, "title")
            item_title.text = title
            
            mastery = ET.SubElement(item, "adlcp:masteryscore")
            mastery.text = str(config.SCORM_MASTERY_SCORE)

            resources = ET.SubElement(manifest, "resources")
            resource = ET.SubElement(resources, "resource")
            resource.set("identifier", "resource-1")
            resource.set("type", "webcontent")
            resource.set("adlcp:scormtype", "sco")
            resource.set("href", "index.html")

            for fname in ["index.html", "style.css", "scorm_api.js"]:
                f = ET.SubElement(resource, "file")
                f.set("href", fname)
        else:
            resources = ET.SubElement(manifest, "resources")
            for page_idx, page in enumerate(pages):
                page_id = page_idx + 1
                page_title_text = page.get("title", f"Page {page_id}")
                
                # Item
                item = ET.SubElement(org, "item")
                item.set("identifier", f"item-{page_id}")
                item.set("identifierref", f"resource-{page_id}")
                item.set("isvisible", "true")
                
                item_title = ET.SubElement(item, "title")
                item_title.text = page_title_text
                
                mastery = ET.SubElement(item, "adlcp:masteryscore")
                mastery.text = str(config.SCORM_MASTERY_SCORE)
                
                # Resource
                resource = ET.SubElement(resources, "resource")
                resource.set("identifier", f"resource-{page_id}")
                resource.set("type", "webcontent")
                resource.set("adlcp:scormtype", "sco")
                resource.set("href", f"page_{page_id}.html")
                
                # Files
                f1 = ET.SubElement(resource, "file")
                f1.set("href", f"page_{page_id}.html")
                f2 = ET.SubElement(resource, "file")
                f2.set("href", "style.css")
                f3 = ET.SubElement(resource, "file")
                f3.set("href", "scorm_api.js")

        # Format XML (#10 — ET.indent instead of minidom)
        ET.indent(manifest, space="  ")
        xml_str = ET.tostring(manifest, encoding="unicode", xml_declaration=False)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str

    # ------------------------------------------------------------------
    # Рендеринг HTML
    # ------------------------------------------------------------------

    def _render_html(self, course: dict) -> str:
        """Рендеринг HTML-страницы из Jinja2 шаблона (Legacy Mono-SCO)."""
        template = self.env.get_template("index.html")
        return template.render(
            title=course.get("title", "Untitled"),
            description=course.get("description", ""),
            language=course.get("language", config.DEFAULT_COURSE_LANGUAGE),
            pages=course.get("pages", []),
        )

    def _render_page_html(self, course: dict, page: dict, page_idx: int) -> str:
        """Рендеринг HTML для отдельной страницы (Multi-SCO)."""
        # Пытаемся использовать page.html, если нет - фоллбэк на index.html
        try:
            template = self.env.get_template("page.html")
        except:
            return self._render_html(course)
            
        return template.render(
            title=course.get("title", "Untitled"),
            language=course.get("language", config.DEFAULT_COURSE_LANGUAGE),
            page=page,
            page_idx=page_idx,
            total_pages=len(course.get("pages", [])),
        )

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _read_template_file(self, filename: str) -> str:
        """Чтение статического файла из папки шаблонов."""
        path = os.path.join(self.templates_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _create_zip(files: dict[str, str], output_path: str) -> None:
        """Создание ZIP-архива из словаря {filename: content}."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)

    @staticmethod
    def _slugify(text: str) -> str:
        """Простая транслитерация и slugify для идентификаторов."""
        translit = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
            "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k",
            "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
            "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
            "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",
            "ь": "", "э": "e", "ю": "yu", "я": "ya",
        }
        result = []
        for char in text.lower():
            if char in translit:
                result.append(translit[char])
            elif char.isascii() and (char.isalnum() or char in "-_"):
                result.append(char)
            elif char in " \t":
                result.append("-")
        slug = "".join(result)
        # Collapse multiple hyphens (#9 — re.sub instead of while loop)
        slug = re.sub(r'-{2,}', '-', slug)
        return slug.strip("-") or "course"
