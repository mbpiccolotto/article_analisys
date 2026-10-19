"""Etapa 1 de 5 · Base: configuração, modelo de dados e utilitários de texto.

Sequência do programa: base -> input -> analisys -> output -> server.
Cada etapa só importa das anteriores.
"""

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================================
# Configuração: caminhos, limites e constantes compartilhadas
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "interface"

# Armazenamento local (estilo servidor): guarda apenas os filtros da última sessão.
DATA_DIR = Path(os.environ.get("TRIAGEM_DADOS") or PROJECT_ROOT / "cache")
LAST_SESSION_FILE = DATA_DIR / "last_session.json"

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
HEALTH_TOKEN = "triagem-artigos"  # o launch.bat confere esta resposta em /healthz


def source_fingerprint() -> str:
    """Resumo do código e da interface. O servidor o informa em /healthz e o inicializador o
    compara com os arquivos atuais, para não reutilizar um servidor aberto com código antigo."""
    digest = hashlib.sha1()
    for folder, pattern in ((PROJECT_ROOT / "scripts", "*.py"), (FRONTEND_DIR, "*")):
        for path in sorted(folder.glob(pattern)):
            if path.is_file():
                digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()[:12]


# Limites de validação dos filtros recebidos da interface.
MAX_FILTERS = 30
MAX_TERMS_PER_FILTER = 50
MAX_TEXT_LENGTH = 120
MAX_WEIGHT = 100

# Modelo visual do fluxograma PRISMA (o primeiro encontrado é usado).
PRISMA_TEMPLATE_PATHS = (
    PROJECT_ROOT / "prisma.svg",
    Path(r"C:\Users\mathe\OneDrive\Documentos\Artigos\prisma.svg"),
    Path(r"C:\Users\mathe\OneDrive\Documentos\prisma.svg"),
)


# ============================================================================
# Modelo de dados e constantes de decisão
# ============================================================================

INCLUDED = "Incluído"
EXCLUDED = "Excluído"
NOT_IDENTIFIED = "Não identificado"
UNTITLED_RECORD = "Título não identificado"
OTHER_SOURCES = "Outras fontes"


@dataclass
class Upload:
    """Arquivo recebido do navegador: nome (com a pasta, se enviado por pasta) e conteúdo."""

    filename: str
    data: bytes


@dataclass
class Article:
    filename: str
    source_type: str = "RIS"  # formato do arquivo de origem (RIS, BibTeX, CSV, PubMed, EndNote)
    title: str = NOT_IDENTIFIED
    year: str = NOT_IDENTIFIED
    doi: str = NOT_IDENTIFIED
    abstract: str = NOT_IDENTIFIED
    decision: str = EXCLUDED
    rationale: str = "Não foi possível reunir evidências suficientes."
    relevance_score: float = 0
    maximum_score: float = 0
    criteria_met: list[str] = field(default_factory=list)
    criteria_missing: list[str] = field(default_factory=list)
    filter_results: list[dict[str, Any]] = field(default_factory=list)
    exclusion_reason: str = ""
    exclusion_group: str = ""  # filtro (ou motivo) que classifica a exclusão no PRISMA; um único grupo por artigo
    ris_record: str = ""  # registro RIS original (só para registros vindos de RIS)
    authors: str = "Não identificado automaticamente"
    journal: str = "A preencher na revisão integral"
    extraction_note: str | None = None
    repository: str = OTHER_SOURCES
    duplicate_of: str | None = None
    duplicate_reason: str | None = None


# ============================================================================
# Normalização e utilitários de texto
# ============================================================================

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
_WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def text_key(value: str) -> str:
    """Normaliza acentos para comparações simples e previsíveis de termos."""
    return " ".join(
        "".join(char for char in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(char) != "Mn").split()
    )


def display_score(value: int | float) -> str:
    return str(int(value)) if value == int(value) else f"{value:.1f}".replace(".", ",")


def parse_decimal(value: Any) -> float:
    """Aceita vírgula ou ponto como separador decimal nos valores da interface."""
    if isinstance(value, (int, float)):
        return float(value)
    number = str(value).strip().replace(" ", "")
    if "," in number and "." in number:
        decimal_separator = "," if number.rfind(",") > number.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        number = number.replace(thousands_separator, "").replace(decimal_separator, ".")
    else:
        number = number.replace(",", ".")
    return float(number)


def secure_filename(filename: str) -> str:
    """Nome de arquivo seguro e só com ASCII (mesma regra do werkzeug.utils.secure_filename)."""
    filename = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    for separator in (os.sep, os.path.altsep):
        if separator:
            filename = filename.replace(separator, " ")
    filename = _UNSAFE_FILENAME_CHARS.sub("", "_".join(filename.split())).strip("._")
    if os.name == "nt" and filename and filename.split(".")[0].upper() in _WINDOWS_DEVICE_NAMES:
        filename = f"_{filename}"
    return filename
