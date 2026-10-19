"""Etapa 2 de 5 · Entrada: leitura de RIS e conversão de BibTeX, CSV, PubMed e EndNote para RIS.

Sequência do programa: base -> input -> analisys -> output -> server.
Cada etapa só importa das anteriores.
"""

import csv
import re
import unicodedata

from .base import normalize, OTHER_SOURCES, text_key, Upload


# ============================================================================
# Leitura de RIS: decodificação, registros e metadados
# ============================================================================

RisRecord = dict[str, list[str]]

YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
RIS_TAG_PATTERN = re.compile(r"^([A-Z0-9]{2})\s{0,2}-\s?(.*)$")

REPOSITORY_MARKERS = (
    ("Scopus", ("scopus",)),
    ("IEEE Xplore", ("ieee", "ieeexplore")),
    ("Web of Science", ("web of science", "webofscience", "clarivate", "wos")),
)


def find_year(text: str) -> str | None:
    match = YEAR_PATTERN.search(text)
    return match.group(0) if match else None


def find_doi(text: str) -> str | None:
    match = DOI_PATTERN.search(text)
    return match.group(0).rstrip(".,;) ]") if match else None


def detect_repository(source_name: str, record: RisRecord | None = None) -> str:
    """Infere a base bibliográfica a partir do nome do arquivo e dos metadados do registro."""
    metadata = " ".join(value for values in (record or {}).values() for value in values)
    source = text_key(f"{source_name} {metadata}")
    for repository, markers in REPOSITORY_MARKERS:
        if any(marker in source for marker in markers):
            return repository
    return OTHER_SOURCES


# --------------------------------------------------------------------------- RIS


def decode_ris(raw: bytes) -> tuple[str, str | None]:
    if not raw.strip():
        return "", "O arquivo está vazio."
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return "", "Não foi possível identificar a codificação do arquivo."


def parse_ris(text: str) -> list[RisRecord]:
    records: list[RisRecord] = []
    current: RisRecord | None = None
    previous_tag: str | None = None
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = RIS_TAG_PATTERN.match(raw_line)
        if match:
            tag, value = match.groups()
            if tag == "TY":
                if current:
                    records.append(current)
                current, previous_tag = {"TY": [value.strip()]}, "TY"
            elif current is not None and tag == "ER":
                records.append(current)
                current, previous_tag = None, None
            elif current is not None:
                current.setdefault(tag, []).append(value.strip())
                previous_tag = tag
        elif current is not None and previous_tag and raw_line.strip():
            current[previous_tag][-1] = f"{current[previous_tag][-1]} {raw_line.strip()}".strip()
    if current:
        records.append(current)
    return records


def format_ris(record: RisRecord) -> str:
    """Reescreve um registro lido por parse_ris no formato RIS (TY primeiro, ER por último)."""
    lines = [f"TY  - {record['TY'][0]}"]
    for tag, values in record.items():
        if tag not in ("TY", "ER"):
            lines.extend(f"{tag}  - {value}" for value in values if value)
    lines.append("ER  - ")
    return "\n".join(lines)


def ris_value(record: RisRecord, *tags: str) -> str:
    """Primeiro valor não vazio entre as tags informadas (em ordem de prioridade)."""
    for tag in tags:
        values = [normalize(value) for value in record.get(tag, []) if normalize(value)]
        if values:
            return values[0]
    return ""


# ============================================================================
# Conversão para RIS: BibTeX, CSV, PubMed/MEDLINE e EndNote
# ============================================================================

csv.field_size_limit(1 << 24)  # resumos longos em CSV

# extensão -> formato lido. ".txt" é identificado pelo conteúdo (ver sniff_format).
FORMATS = {".ris": "RIS", ".bib": "BibTeX", ".bibtex": "BibTeX", ".nbib": "PubMed", ".medline": "PubMed", ".enw": "EndNote", ".csv": "CSV", ".txt": "auto"}
ALLOWED_EXTENSIONS = tuple(FORMATS)
FORMAT_NAMES = "RIS, BibTeX (.bib), CSV, PubMed (.nbib) ou EndNote (.enw)"


def read_records(upload: Upload) -> tuple[list[RisRecord], str, str | None]:
    """(registros, formato, erro). Em caso de erro, a lista vem vazia e a mensagem explica o motivo."""
    extension = "." + upload.filename.lower().rsplit(".", 1)[-1] if "." in upload.filename else ""
    kind = FORMATS.get(extension, "")
    text, error = decode_ris(upload.data)
    if error:
        return [], kind, error
    if kind == "auto":
        kind = sniff_format(text)
    readers = {"RIS": parse_ris, "BibTeX": parse_bibtex, "PubMed": parse_medline, "EndNote": parse_endnote, "CSV": parse_csv}
    if kind not in readers:
        return [], kind, f"Formato não reconhecido. Use {FORMAT_NAMES}."
    records = [record for record in readers[kind](text) if record.get("TI") or record.get("T1") or record.get("AB")]
    if not records:
        hint = "Verifique se o arquivo contém linhas TY  - e ER  -." if kind == "RIS" else "Nenhum registro com título ou resumo foi encontrado."
        return [], kind, f"Nenhum registro válido foi encontrado ({kind}). {hint}"
    return records, kind, None


def sniff_format(text: str) -> str:
    head = text[:4000]
    if re.search(r"^TY\s{1,2}-", head, re.M):
        return "RIS"
    if re.search(r"^PMID- ", head, re.M):
        return "PubMed"
    if re.search(r"^%0 ", head, re.M):
        return "EndNote"
    if re.search(r"^\s*@\w+\s*[{(]", head, re.M):
        return "BibTeX"
    return ""


def to_ris(records: list[RisRecord]) -> str:
    return "\n\n".join(format_ris(record) for record in records) + "\n" if records else ""


# --------------------------------------------------------------------------- utilidades


def _add(record: RisRecord, tag: str, value: str | None) -> None:
    value = " ".join((value or "").split())
    if value:
        record.setdefault(tag, []).append(value)


def _add_pages(record: RisRecord, pages: str) -> None:
    parts = [part.strip() for part in re.split(r"\s*[-–—]+\s*", pages.strip(), maxsplit=1)]
    if parts and parts[0]:
        _add(record, "SP", parts[0])
        if len(parts) > 1 and parts[1]:
            end = parts[1]
            if end.isdigit() and parts[0].isdigit() and len(end) < len(parts[0]):  # "123-30" -> 130
                end = parts[0][:len(parts[0]) - len(end)] + end
            _add(record, "EP", end)


def _add_author(record: RisRecord, name: str) -> None:
    """Autor no formato RIS "Sobrenome, Nome"; nomes já com vírgula (ou institucionais longos) ficam como estão."""
    name = " ".join(name.split())
    if name and "," not in name and 2 <= len(name.split()) <= 4 and not name.isupper():
        *first, last = name.split()
        # "Silva M." / "Silva JB" já vêm como sobrenome + iniciais; "Maria Silva" vira "Silva, Maria"
        name = f"{' '.join(first)}, {last}" if re.fullmatch(r"[A-Z][A-Z.\-]{0,4}", last) else f"{last}, {' '.join(first)}"
    _add(record, "AU", name)


def _add_keywords(record: RisRecord, value: str) -> None:
    for keyword in re.split(r"[;,]", value):
        _add(record, "KW", keyword)


_ACCENTS = {"`": "\u0300", "'": "\u0301", "^": "\u0302", "~": "\u0303", '"': "\u0308", "=": "\u0304", ".": "\u0307"}
_ACCENT_LETTERS = {"c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b"}


def _clean_tex(value: str) -> str:
    """Remove chaves e comandos LaTeX comuns (acentos, \\&, ~) de campos BibTeX."""
    value = re.sub(r"\\([`'^~\"=.])\s*\{?\\?([A-Za-z])\}?", lambda m: m.group(2) + _ACCENTS[m.group(1)], value)
    value = re.sub(r"\\([cvuH])\s*\{?([A-Za-z])\}?", lambda m: m.group(2) + _ACCENT_LETTERS[m.group(1)], value)
    value = re.sub(r"\\[A-Za-z]+\*?\s*", lambda m: "ß" if m.group(0).startswith("\\ss") else ("ø" if m.group(0).startswith("\\o") and m.group(0).strip() == "\\o" else ""), value)
    value = value.replace("\\ss", "ß").replace("\\o ", "ø").replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("\\#", "#").replace("~", " ")
    return unicodedata.normalize("NFC", re.sub(r"[{}]", "", value)).strip()


# --------------------------------------------------------------------------- BibTeX

_BIBTEX_TYPES = {"article": "JOUR", "inproceedings": "CONF", "conference": "CONF", "proceedings": "CONF", "book": "BOOK", "inbook": "CHAP", "incollection": "CHAP",
                 "phdthesis": "THES", "mastersthesis": "THES", "thesis": "THES", "techreport": "RPRT", "report": "RPRT", "unpublished": "UNPB", "online": "ELEC"}
_BIBTEX_FIELD = re.compile(r"\s*,?\s*([A-Za-z][\w:-]*)\s*=\s*")


def parse_bibtex(text: str) -> list[RisRecord]:
    records: list[RisRecord] = []
    macros: dict[str, str] = {}  # @string{nome = "valor"}
    position = 0
    while (start := text.find("@", position)) >= 0:
        header = re.compile(r"@\s*([A-Za-z]+)\s*([{(])").match(text, start)
        if not header:
            position = start + 1
            continue
        end = _closing(text, header.end(), header.group(2))
        position = end + 1
        kind = header.group(1).lower()
        if kind == "string":
            macros.update({name: _clean_tex(value) for name, value in _bibtex_fields("," + text[header.end():end], {}).items()})
            continue
        if kind in ("comment", "preamble"):
            continue
        fields = _bibtex_fields(text[header.end():end], macros)  # valores brutos (com chaves), para reconhecer autores institucionais
        field = lambda *names: next((_clean_tex(fields[name]) for name in names if fields.get(name)), "")
        record: RisRecord = {"TY": [_BIBTEX_TYPES.get(kind, "GEN")]}
        _add(record, "TI", field("title"))
        for author in re.split(r"\s+and\s+", fields.get("author", ""), flags=re.I):
            if re.fullmatch(r"\{[^{}]*\}", author.strip()):  # {World Health Organization}: autor institucional, sem inversão
                _add(record, "AU", _clean_tex(author))
            else:
                _add_author(record, _clean_tex(author))
        _add(record, "PY", find_year(field("year", "date")))
        _add(record, "JO", field("journal", "journaltitle"))
        _add(record, "T2", field("booktitle"))
        _add(record, "VL", field("volume"))
        _add(record, "IS", field("number", "issue"))
        _add_pages(record, field("pages"))
        _add(record, "PB", field("publisher"))
        _add(record, "SN", field("issn", "isbn"))
        _add(record, "DO", field("doi"))
        _add(record, "AB", field("abstract"))
        _add(record, "UR", field("url"))
        _add(record, "LA", field("language"))
        _add_keywords(record, field("keywords", "keyword"))
        records.append(record)
    return records


def _closing(text: str, start: int, opener: str) -> int:
    """Posição do delimitador que fecha o bloco aberto antes de `start` (ou o fim do texto)."""
    closer = "}" if opener == "{" else ")"
    depth, index = 1, start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        depth += (char == opener) - (char == closer)
        if depth == 0:
            return index
        index += 1
    return len(text)


def _bibtex_fields(body: str, macros: dict[str, str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    position = body.find(",") + 1
    while position and (match := _BIBTEX_FIELD.match(body, position)):
        value, position = _bibtex_value(body, match.end(), macros)
        fields.setdefault(match.group(1).lower(), value)
    return fields


def _bibtex_value(body: str, position: int, macros: dict[str, str]) -> tuple[str, int]:
    parts: list[str] = []
    while True:
        position = len(body) - len(body[position:].lstrip())
        char = body[position:position + 1]
        if char == "{":
            end = _closing(body, position + 1, "{")
            parts.append(body[position + 1:end])
            position = end + 1
        elif char == '"':
            end = position + 1
            while end < len(body) and not (body[end] == '"' and body[end - 1] != "\\"):
                end += 1
            parts.append(body[position + 1:end])
            position = end + 1
        else:
            token = re.compile(r"[^\s,#]+").match(body, position)
            if not token:
                return "".join(parts), position
            parts.append(macros.get(token.group(0).lower(), token.group(0)))  # número, mês ou macro de @string
            position = token.end()
        position = len(body) - len(body[position:].lstrip())
        if body[position:position + 1] != "#":
            return "".join(parts), position
        position += 1


# --------------------------------------------------------------------------- PubMed / MEDLINE (.nbib)

_MEDLINE_LINE = re.compile(r"^([A-Z][A-Z0-9]{1,3}) {0,2}- ?(.*)$")


def parse_medline(text: str) -> list[RisRecord]:
    blocks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _MEDLINE_LINE.match(line)
        if match:
            if match.group(1) == "PMID" and current:
                blocks.append(current)
                current = []
            current.append((match.group(1), match.group(2).strip()))
        elif line.startswith("      ") and current:  # continuação do campo anterior
            current[-1] = (current[-1][0], f"{current[-1][1]} {line.strip()}")
        elif not line.strip() and current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    records = []
    for block in blocks:
        record: RisRecord = {"TY": ["JOUR"]}
        authors_full = [value for tag, value in block if tag == "FAU"]
        for tag, value in block:
            if tag == "PMID":
                _add(record, "AN", value)
            elif tag == "TI":
                _add(record, "TI", value)
            elif tag == "AB":
                _add(record, "AB", value)
            elif tag == "AU" and not authors_full:
                _add(record, "AU", value)
            elif tag == "FAU":
                _add(record, "AU", value)
            elif tag == "DP":
                _add(record, "PY", find_year(value))
            elif tag == "JT":
                _add(record, "JO", value)
            elif tag == "VI":
                _add(record, "VL", value)
            elif tag == "IP":
                _add(record, "IS", value)
            elif tag == "PG":
                _add_pages(record, value)
            elif tag in ("AID", "LID") and value.endswith("[doi]") and "DO" not in record:
                _add(record, "DO", value[:-5].strip())
            elif tag in ("OT", "MH"):
                _add(record, "KW", re.sub(r"^\*", "", value))
            elif tag == "LA":
                _add(record, "LA", value)
            elif tag == "IS" and "SN" not in record:
                _add(record, "SN", value.split(" ")[0])
        if "JO" not in record:  # sem título completo: usa a abreviatura
            _add(record, "JO", next((value for tag, value in block if tag == "TA"), ""))
        records.append(record)
    return records


# --------------------------------------------------------------------------- EndNote (tagged, .enw)

_ENDNOTE_TYPES = {"journal article": "JOUR", "conference paper": "CONF", "conference proceedings": "CONF", "book": "BOOK", "book section": "CHAP", "thesis": "THES", "report": "RPRT", "web page": "ELEC"}


def parse_endnote(text: str) -> list[RisRecord]:
    records: list[RisRecord] = []
    record: RisRecord | None = None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = re.match(r"^%(\S) ?(.*)$", line)
        if not match:
            continue
        tag, value = match.groups()
        if tag == "0":
            record = {"TY": [_ENDNOTE_TYPES.get(value.strip().lower(), "GEN")]}
            records.append(record)
        elif record is not None:
            if tag == "T":
                _add(record, "TI", value)
            elif tag == "A":
                _add_author(record, value)
            elif tag == "D":
                _add(record, "PY", find_year(value))
            elif tag == "J":
                _add(record, "JO", value)
            elif tag == "B":
                _add(record, "T2", value)
            elif tag == "V":
                _add(record, "VL", value)
            elif tag == "N":
                _add(record, "IS", value)
            elif tag == "P":
                _add_pages(record, value)
            elif tag == "R":
                _add(record, "DO", find_doi(value) or value)
            elif tag == "X":
                _add(record, "AB", value)
            elif tag == "K":
                _add_keywords(record, value)
            elif tag == "U":
                _add(record, "UR", value)
            elif tag == "@":
                _add(record, "SN", value)
            elif tag == "I":
                _add(record, "PB", value)
            elif tag == "G":
                _add(record, "LA", value)
    return records


# --------------------------------------------------------------------------- CSV (Scopus, Web of Science, IEEE Xplore, PubMed...)

# campo RIS -> nomes de coluna aceitos (minúsculos); a primeira coluna presente e preenchida vence.
_CSV_COLUMNS = {
    "TI": ("title", "article title", "document title", "ti"),
    "AB": ("abstract", "ab"),
    "JO": ("source title", "publication title", "journal", "journal/book", "journal title", "so"),
    "PY": ("year", "publication year", "py", "create date", "publication date"),
    "DO": ("doi", "di"),
    "VL": ("volume", "vl"),
    "IS": ("issue", "number", "is"),
    "SN": ("issn", "sn"),
    "PB": ("publisher", "pu"),
    "UR": ("link", "url", "pdf link", "ur"),
    "LA": ("language of original document", "language", "la"),
    "DB": ("source", "database", "db"),
}
_CSV_AUTHORS = ("author full names", "authors", "author(s)", "author", "au", "af")
_CSV_KEYWORDS = ("author keywords", "keywords", "author keyword", "de", "index keywords", "ieee terms")
_CSV_TYPES = {"article": "JOUR", "review": "JOUR", "journal article": "JOUR", "conference paper": "CONF", "conference": "CONF", "proceedings paper": "CONF",
              "book": "BOOK", "book chapter": "CHAP", "chapter": "CHAP", "thesis": "THES", "report": "RPRT"}


def parse_csv(text: str) -> list[RisRecord]:
    first_line = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first_line.count)
    reader = csv.reader(text.splitlines(keepends=True), delimiter=delimiter)
    header = next(reader, [])
    names = [" ".join(name.lower().split()) for name in header]
    if not any(name in _CSV_COLUMNS["TI"] or name in _CSV_COLUMNS["AB"] for name in names):
        return []

    def pick(row: list[str], candidates: tuple[str, ...]) -> str:
        for candidate in candidates:
            if candidate in names and names.index(candidate) < len(row) and row[names.index(candidate)].strip():
                return row[names.index(candidate)].strip()
        return ""

    records = []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        record: RisRecord = {"TY": [_CSV_TYPES.get(pick(row, ("document type", "type", "publication type", "content type", "dt")).lower(), "JOUR")]}
        for tag, candidates in _CSV_COLUMNS.items():
            value = pick(row, candidates)
            _add(record, tag, find_year(value) if tag == "PY" else (find_doi(value) or value) if tag == "DO" else value)
        authors = re.sub(r"\s*\(\d+\)", "", pick(row, _CSV_AUTHORS))  # Scopus: "Silva, Maria (12345)"
        if ";" in authors:
            names_ = authors.split(";")
        elif re.search(r"\sand\s", authors):
            names_ = re.split(r"\sand\s", authors)
        elif authors.count(",") and all(" " in part.strip() for part in authors.split(",")):  # "Silva M, Souza J"
            names_ = authors.split(",")
        else:
            names_ = [authors]
        for name in names_:
            _add_author(record, name)
        _add_keywords(record, pick(row, _CSV_KEYWORDS))
        records.append(record)
    return records
