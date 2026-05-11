"""Per-parser document extension sets for the ETL pipeline.

Every consumer (file_classifier, connector-level skip checks, ETL pipeline
validation) imports from here so there is a single source of truth.

Extensions already covered by PLAINTEXT_EXTENSIONS, AUDIO_EXTENSIONS, or
DIRECT_CONVERT_EXTENSIONS in file_classifier are NOT repeated here -- these
sets are exclusively for the "document" ETL path (Docling / LlamaParse /
Unstructured).

Image extensions intentionally remain in the per-parser sets for fallback
compatibility.  IMAGE_EXTENSIONS is used only for routing classification.
"""

from pathlib import PurePosixPath


def _mineru_supports_office_formats() -> bool:
    """Return True when installed MinerU version supports Office files.

    MinerU v3+ adds native Office parsing support (DOCX/PPTX/XLSX).
    """
    def _major_version(dist_name: str) -> int | None:
        from importlib.metadata import version

        try:
            raw = version(dist_name)
            major_str = raw.split(".", 1)[0]
            return int(major_str)
        except Exception:
            return None

    try:
        # Modern package name: mineru
        major = _major_version("mineru")
        if major is not None:
            return major >= 3

        # Legacy distribution used in some installs while runtime module
        # remains `magic_pdf`.
        major = _major_version("magic-pdf")
        if major is not None:
            return major >= 3

        # Fallback legacy naming seen in some environments.
        major = _major_version("magic_pdf")
        if major is not None:
            return major >= 3

        return False
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Image extensions (used by file_classifier for routing to vision LLM)
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".svg",
        ".heic",
        ".heif",
    }
)

# ---------------------------------------------------------------------------
# Per-parser document extension sets (from official documentation)
# ---------------------------------------------------------------------------

DOCLING_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".webp",
    }
)

MINERU_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
    }
)

MINERU_OFFICE_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".docx",
        ".pptx",
        ".xlsx",
    }
)

LLAMAPARSE_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".docm",
        ".dot",
        ".dotm",
        ".pptm",
        ".pot",
        ".potx",
        ".xlsm",
        ".xlsb",
        ".xlw",
        ".rtf",
        ".epub",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".svg",
        ".odt",
        ".ods",
        ".odp",
        ".hwp",
        ".hwpx",
    }
)

UNSTRUCTURED_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tiff",
        ".tif",
        ".heic",
        ".rtf",
        ".epub",
        ".odt",
        ".eml",
        ".msg",
        ".p7s",
    }
)

AZURE_DI_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tiff",
        ".tif",
        ".heif",
    }
)

# ---------------------------------------------------------------------------
# Union (used by classify_file for routing) + service lookup
# ---------------------------------------------------------------------------

DOCUMENT_EXTENSIONS: frozenset[str] = (
    MINERU_DOCUMENT_EXTENSIONS
    | DOCLING_DOCUMENT_EXTENSIONS
    | LLAMAPARSE_DOCUMENT_EXTENSIONS
    | UNSTRUCTURED_DOCUMENT_EXTENSIONS
    | AZURE_DI_DOCUMENT_EXTENSIONS
)

_SERVICE_MAP: dict[str, frozenset[str]] = {
    "MINERU": MINERU_DOCUMENT_EXTENSIONS,
    "DOCLING": DOCLING_DOCUMENT_EXTENSIONS,
    "LLAMACLOUD": LLAMAPARSE_DOCUMENT_EXTENSIONS,
    "UNSTRUCTURED": UNSTRUCTURED_DOCUMENT_EXTENSIONS,
}


def get_document_extensions_for_service(etl_service: str | None) -> frozenset[str]:
    """Return the document extensions supported by *etl_service*.

    When *etl_service* is ``LLAMACLOUD`` and Azure Document Intelligence
    credentials are configured, the set is dynamically expanded to include
    Azure DI's supported extensions (e.g. ``.heif``).

    Falls back to the full union when the service is ``None`` or unknown.
    """
    extensions = _SERVICE_MAP.get(etl_service or "", DOCUMENT_EXTENSIONS)
    if etl_service == "MINERU" and _mineru_supports_office_formats():
        extensions = extensions | MINERU_OFFICE_DOCUMENT_EXTENSIONS
    if etl_service == "LLAMACLOUD":
        from app.config import config as app_config

        if getattr(app_config, "AZURE_DI_ENDPOINT", None) and getattr(
            app_config, "AZURE_DI_KEY", None
        ):
            extensions = extensions | AZURE_DI_DOCUMENT_EXTENSIONS
    return extensions


def is_supported_document_extension(filename: str) -> bool:
    """Return True if the file's extension is in the supported document set."""
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix in DOCUMENT_EXTENSIONS
