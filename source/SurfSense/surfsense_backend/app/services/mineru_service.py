import asyncio
import importlib
import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MinerUService:
    """MinerU document processing service."""

    def __init__(self):
        MagicPDF = None
        self._fallback_do_parse = None
        self._fallback_read_fn = None
        self._fallback_make_mode = None
        import_errors: list[str] = []

        for module_name in ("mineru", "magic_pdf"):
            try:
                module = importlib.import_module(module_name)
                MagicPDF = getattr(module, "MagicPDF", None)
                if MagicPDF is not None:
                    break
                import_errors.append(
                    f"module '{module_name}' imported but MagicPDF symbol not found"
                )
            except Exception as exc:
                import_errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

        self._extractor_cls = MagicPDF

        if self._extractor_cls is None:
            try:
                from mineru.cli.common import MakeMode, do_parse, read_fn

                self._fallback_do_parse = do_parse
                self._fallback_read_fn = read_fn
                self._fallback_make_mode = MakeMode
            except Exception as exc:
                import_errors.append(
                    f"mineru.cli.common fallback unavailable: {type(exc).__name__}: {exc}"
                )

        if self._extractor_cls is None and self._fallback_do_parse is None:
            raise RuntimeError(
                "MinerU is not available. Install from official repo "
                "https://github.com/opendatalab/mineru "
                "(e.g. `uv pip install -U \"mineru[all]\"` or source install). "
                "Runtime import compatibility: `mineru` (preferred) or `magic_pdf` (legacy). "
                f"details: {'; '.join(import_errors)}"
            )

    @staticmethod
    def _extract_content(result: Any) -> str:
        if result is None:
            return ""

        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            for key in ("content_markdown", "markdown", "content", "text"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return ""

        for attr in ("content_markdown", "markdown", "content", "text"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value.strip():
                return value

        return ""

    def _process_sync(self, file_path: str, filename: str) -> dict[str, Any]:
        if self._extractor_cls is not None:
            extractor = self._extractor_cls(str(file_path))

            if not hasattr(extractor, "extract"):
                raise RuntimeError("MinerU extractor has no extract() method")

            result = extractor.extract()
            content = self._extract_content(result)
        else:
            source_path = Path(file_path)
            source_stem = Path(filename).stem or source_path.stem or "document"

            with tempfile.TemporaryDirectory(prefix="mineru_out_") as output_dir:
                file_bytes = self._fallback_read_fn(source_path)
                self._fallback_do_parse(
                    output_dir=output_dir,
                    pdf_file_names=[source_stem],
                    pdf_bytes_list=[file_bytes],
                    p_lang_list=["en"],
                    backend="pipeline",
                    parse_method="auto",
                    formula_enable=True,
                    table_enable=True,
                    f_draw_layout_bbox=False,
                    f_draw_span_bbox=False,
                    f_dump_md=True,
                    f_dump_middle_json=False,
                    f_dump_model_output=False,
                    f_dump_orig_pdf=False,
                    f_dump_content_list=False,
                    f_make_md_mode=self._fallback_make_mode.MM_MD,
                )

                output_root = Path(output_dir)
                primary_md = output_root / source_stem
                md_candidates = list(primary_md.rglob(f"{source_stem}.md"))
                if not md_candidates:
                    md_candidates = list(output_root.rglob("*.md"))

                if not md_candidates:
                    raise RuntimeError(
                        f"MinerU fallback parse completed but no markdown output found for {filename}"
                    )

                content = md_candidates[0].read_text(encoding="utf-8", errors="ignore")

        if not content.strip():
            raise RuntimeError(f"MinerU returned empty content for {filename}")

        return {
            "content": content,
            "service_used": "mineru",
            "processing_notes": "Processed with MinerU (module import: mineru or magic_pdf)",
            "source_file": Path(filename).name,
        }

    async def process_document(self, file_path: str, filename: str) -> dict[str, Any]:
        logger.info("Processing %s with MinerU", filename)
        return await asyncio.to_thread(self._process_sync, file_path, filename)


def create_mineru_service() -> MinerUService:
    return MinerUService()
