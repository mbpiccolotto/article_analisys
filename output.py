"""Etapa 4 de 5 · Saída: planilhas Excel (escritor .xlsx próprio), RIS dos incluídos e PRISMA (planilha e SVG).

Sequência do programa: base -> input -> analisys -> output -> server.
Cada etapa só importa das anteriores.
"""

import io
import re
import zipfile
from xml.sax.saxutils import escape

from .base import display_score, INCLUDED, OTHER_SOURCES, PRISMA_TEMPLATE_PATHS


# ============================================================================
# Escritor de .xlsx (zip + XML)
# ============================================================================

DEFAULT, HEADER, BODY, NOTE = range(4)  # índices dos estilos em STYLES_XML (cellXfs)

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")  # inválidos em XML (comuns em texto extraído de PDF)

STYLES_XML = (
    f'<styleSheet xmlns="{_NS}">'
    '<fonts count="3">'
    '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b val="1"/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>'
    '<font><b val="1"/><sz val="11"/><color rgb="FF7F6000"/><name val="Arial"/></font>'
    '</fonts>'
    '<fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFDDEBF7"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/></patternFill></fill></fills>'
    '<borders count="3"><border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left/><right/><top/><bottom style="thin"><color rgb="FFB7C9DA"/></bottom><diagonal/></border>'
    '<border><left style="medium"><color rgb="FFBF9000"/></left><right style="thin"><color rgb="FFBF9000"/></right>'
    '<top style="thin"><color rgb="FFBF9000"/></top><bottom style="thin"><color rgb="FFBF9000"/></bottom><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="2" fillId="4" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def column_letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class Sheet:
    """Uma aba: células esparsas (linha, coluna) -> (valor, estilo)."""

    def __init__(self, title: str, widths: list[int] | None = None) -> None:
        self.title = title
        self.widths = widths or []
        self.cells: dict[tuple[int, int], tuple[object, int]] = {}
        self.row_heights: dict[int, int] = {}
        self.merges: list[str] = []
        self.freeze_header = False

    def set(self, row: int, column: int, value: object, style: int = BODY) -> None:
        self.cells[(row, column)] = (value, style)

    def merge(self, first_row: int, first_column: int, last_row: int, last_column: int) -> None:
        self.merges.append(f"{column_letter(first_column)}{first_row}:{column_letter(last_column)}{last_row}")

    @classmethod
    def table(cls, title: str, headers: list[str], rows: list[list], widths: list[int]) -> "Sheet":
        """Cabeçalho + linhas com o estilo padrão (uma linha '—' quando não há dados)."""
        sheet = cls(title, widths)
        for column, header in enumerate(headers, start=1):
            sheet.set(1, column, header, HEADER)
        for row_number, row in enumerate(rows or [["—"] * len(headers)], start=2):
            for column, value in enumerate(row, start=1):
                sheet.set(row_number, column, value, BODY)
        sheet.row_heights[1] = 30
        sheet.freeze_header = True
        return sheet

    @property
    def last_row(self) -> int:
        return max((row for row, _ in self.cells), default=1)

    def to_xml(self, selected: bool) -> str:
        last_row = max([self.last_row, *self.row_heights])
        last_column = max((column for _, column in self.cells), default=1)
        view = '<sheetView showGridLines="0" workbookViewId="0"' + (' tabSelected="1"' if selected else "") + ">"
        if self.freeze_header:
            view += '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft"/>'
        view += "</sheetView>"
        columns = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(self.widths, start=1))

        rows = []
        for row_number in range(1, last_row + 1):
            row_cells = "".join(
                _cell_xml(row_number, column, *self.cells[(row_number, column)])
                for column in range(1, last_column + 1)
                if (row_number, column) in self.cells
            )
            height = f' ht="{self.row_heights[row_number]}" customHeight="1"' if row_number in self.row_heights else ""
            if row_cells or height:
                rows.append(f'<row r="{row_number}"{height}>{row_cells}</row>')

        merges = f'<mergeCells count="{len(self.merges)}">' + "".join(f'<mergeCell ref="{ref}"/>' for ref in self.merges) + "</mergeCells>" if self.merges else ""
        return (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{_NS}">'
            f'<dimension ref="A1:{column_letter(last_column)}{last_row}"/><sheetViews>{view}</sheetViews>'
            f'<sheetFormatPr defaultRowHeight="15"/>{"<cols>" + columns + "</cols>" if columns else ""}'
            f'<sheetData>{"".join(rows)}</sheetData>{merges}</worksheet>'
        )


def _cell_xml(row: int, column: int, value: object, style: int) -> str:
    reference = f"{column_letter(column)}{row}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{reference}" s="{style}"><v>{value!r}</v></c>'
    text = _ILLEGAL_XML.sub("", "" if value is None else str(value))
    if not text:
        return f'<c r="{reference}" s="{style}"/>'  # só o estilo (preenchimento/borda)
    return f'<c r="{reference}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def workbook_bytes(sheets: list[Sheet]) -> io.BytesIO:
    """Monta o arquivo .xlsx completo em memória."""
    names = ["[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml"]
    sheet_entries = "".join(f'<sheet name="{escape(sheet.title, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i, sheet in enumerate(sheets, start=1))
    parts = {
        names[0]: (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
            + "</Types>"
        ),
        names[1]: (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        names[2]: (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{_NS}" xmlns:r="{_REL_NS}">'
            f'<bookViews><workbookView/></bookViews><sheets>{sheet_entries}</sheets></workbook>'
        ),
        names[3]: (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="{_REL_NS}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="{_REL_NS}/styles" Target="styles.xml"/></Relationships>'
        ),
        names[4]: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + STYLES_XML,
    }
    for index, sheet in enumerate(sheets, start=1):
        parts[f"xl/worksheets/sheet{index}.xml"] = sheet.to_xml(selected=index == 1)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    output.seek(0)
    return output


# ============================================================================
# Exportações dos resultados: Excel e RIS dos incluídos
# ============================================================================

def build_ris(records: list[dict]) -> io.BytesIO:
    """Arquivo RIS só com os registros incluídos (os de outros formatos já convertidos para RIS)."""
    entries = [article["ris_record"] for article in records if article.get("decision") == INCLUDED and article.get("ris_record")]
    return io.BytesIO(("\n\n".join(entries) + "\n" if entries else "").encode("utf-8"))


def _score(article: dict) -> str:
    return f"{display_score(article.get('relevance_score', 0))}/{display_score(article.get('maximum_score', 0))}"


def _common_columns(article: dict) -> list:
    return [article.get("repository", OTHER_SOURCES), article.get("authors", "Não identificado"), article.get("year", ""), article.get("title", ""), article.get("doi", "")]


def build_excel(records: list[dict]) -> io.BytesIO:
    """Planilha com duas abas: estudos incluídos e excluídos."""
    included, excluded = [], []
    for article in records:
        if article.get("decision") == INCLUDED:
            included.append([f"S{len(included) + 1:02d}", *_common_columns(article), article.get("journal", ""), article.get("abstract", ""), _score(article), "; ".join(article.get("criteria_met", []))])
        else:
            excluded.append([f"{len(excluded) + 1:03d}", *_common_columns(article), article.get("exclusion_reason", ""), _score(article), "; ".join(article.get("criteria_missing", []))])

    return workbook_bytes([
        Sheet.table("Estudos incluídos", ["N.º", "Repositório", "Autor(es)", "Ano", "Título", "DOI", "Periódico", "Resumo", "Pontuação", "Critérios atendidos"], included, [10, 25, 32, 10, 45, 27, 30, 62, 15, 42]),
        Sheet.table("Excluídos", ["N.º", "Repositório", "Autor(es)", "Ano", "Título", "DOI", "Motivo da Exclusão", "Pontuação", "Critérios não atendidos"], excluded, [10, 25, 32, 10, 45, 27, 50, 15, 42]),
    ])


# ============================================================================
# PRISMA 2020: planilha preenchida e fluxograma em SVG
# ============================================================================

REPOSITORIES = ("Scopus", "IEEE Xplore", "Web of Science", OTHER_SOURCES)
MAX_REASON_LINES = 8  # linhas de motivos na caixa de excluídos do fluxograma (o excedente é agrupado)
HUMAN_REVIEW_NOTE = "OBSERVAÇÃO IMPORTANTE: o fluxograma foi preenchido automaticamente a partir da pré-triagem. A leitura crítica do texto completo, a confirmação dos critérios e a decisão de inclusão final devem ser feitas por um pesquisador."


# ----------------------------------------------------------------------- planilha


def build_prisma_excel(records: list[dict], duplicates: list[dict], prisma: dict) -> io.BytesIO:
    """Cria um modelo PRISMA 2020 preenchido até a etapa de pré-triagem."""
    repository_counts = prisma.get("repository_counts", {})
    automatic_rows = [
        ["Identificação", "Registros identificados - Scopus", repository_counts.get("Scopus", 0), "Automático", ""],
        ["Identificação", "Registros identificados - IEEE Xplore", repository_counts.get("IEEE Xplore", 0), "Automático", ""],
        ["Identificação", "Registros identificados - Web of Science", repository_counts.get("Web of Science", 0), "Automático", ""],
        ["Identificação", "Registros identificados - Outras fontes", repository_counts.get("Outras fontes", 0), "Automático", ""],
        ["Identificação", "Total de registros identificados", prisma.get("identified_total", 0), "Automático", "Soma das fontes antes da deduplicação."],
        ["Outros métodos", "Registros identificados - Websites", 0, "Automático", "A fonte ainda não é registrada separadamente pela aplicação."],
        ["Outros métodos", "Registros identificados - Organizações", 0, "Automático", "A fonte ainda não é registrada separadamente pela aplicação."],
        ["Outros métodos", "Registros identificados - Busca por citações", 0, "Automático", "A fonte ainda não é registrada separadamente pela aplicação."],
        ["Antes da triagem", "Registros duplicados removidos", prisma.get("duplicates_removed", 0), "Automático", "Consulte a aba Duplicatas removidas."],
        ["Triagem", "Registros triados", prisma.get("screened", 0), "Automático", "Após a remoção de duplicatas."],
        ["Triagem", "Registros excluídos na pré-triagem", prisma.get("screening_excluded", 0), "Automático", "Exclusão automática pelos critérios configurados."],
        *[["Triagem", f"Excluídos - {reason['label']}", reason["n"], "Automático", "Filtro não atendido; a soma dos motivos é igual aos registros excluídos."] for reason in prisma.get("exclusion_reasons", [])],
        ["Elegibilidade", "Relatórios buscados para obtenção", prisma.get("sought_for_retrieval", 0), "Automático", "Registros pré-incluídos pela triagem."],
        ["Elegibilidade", "Relatórios não obtidos", prisma.get("not_retrieved", 0), "Automático", "Sem falha de obtenção registrada no processamento."],
        ["Elegibilidade", "Relatórios avaliados para elegibilidade", prisma.get("assessed_for_eligibility", 0), "Automático", "Estimativa a partir dos registros pré-incluídos."],
        ["Elegibilidade", "Relatórios excluídos com justificativa", prisma.get("eligibility_excluded", 0), "Automático", "A pré-triagem não substitui a exclusão após leitura integral."],
        ["Outros métodos", "Relatórios buscados, avaliados ou excluídos", 0, "Automático", "Preencha estas fontes no SVG ou na revisão caso sejam utilizadas."],
        ["Incluídos", "Estudos incluídos na revisão", prisma.get("preincluded_studies", 0), "Automático", "Pré-inclusões automáticas; não representam inclusão final."],
    ]
    flow = Sheet.table("Fluxo PRISMA", ["Etapa", "Item PRISMA", "n", "Origem", "Observação"], automatic_rows, [22, 50, 12, 25, 62])
    _add_review_note(flow, len(automatic_rows) + 3)
    return workbook_bytes([
        flow,
        Sheet.table(
            "Por repositório",
            ["Repositório", "Registros identificados", "Critério"],
            [[name, repository_counts.get(name, 0), "Identificados antes da deduplicação"] for name in REPOSITORIES],
            [28, 25, 45],
        ),
        Sheet.table(
            "Duplicatas removidas",
            ["Repositório", "Arquivo / registro", "Título removido", "DOI", "Mantido como", "Critério"],
            [[a.get("repository", OTHER_SOURCES), a.get("filename", ""), a.get("title", ""), a.get("doi", ""), a.get("duplicate_of", ""), a.get("duplicate_reason", "")] for a in duplicates],
            [22, 32, 52, 32, 52, 24],
        ),
        Sheet.table(
            "Registros triados",
            ["Repositório", "Decisão", "Autor(es)", "Ano", "Título", "DOI", "Grupo de exclusão (PRISMA)", "Motivo da exclusão"],
            [[a.get("repository", OTHER_SOURCES), a.get("decision", ""), a.get("authors", ""), a.get("year", ""), a.get("title", ""), a.get("doi", ""), a.get("exclusion_group", ""), a.get("exclusion_reason", "")] for a in records],
            [25, 18, 32, 10, 55, 32, 34, 52],
        ),
    ])


def _add_review_note(sheet: Sheet, first_row: int) -> None:
    """Caixa amarela destacada lembrando que a inclusão final exige análise humana."""
    sheet.set(first_row, 1, HUMAN_REVIEW_NOTE, NOTE)
    sheet.merge(first_row, 1, first_row + 2, 5)
    for offset in range(3):
        sheet.row_heights[first_row + offset] = 26


# --------------------------------------------------------------------------- SVG


def build_prisma_svg(prisma: dict) -> io.BytesIO:
    """Fluxograma PRISMA em SVG: usa o modelo prisma.svg se existir; senão, desenha um padrão."""
    template_path = next((path for path in PRISMA_TEMPLATE_PATHS if path.is_file()), None)
    if template_path:
        svg = _fill_template(template_path.read_text(encoding="utf-8"), prisma)
    else:
        svg = _fallback_svg(prisma)
    return io.BytesIO(svg.encode("utf-8"))


def _flow_numbers(prisma: dict) -> tuple:
    """(identificados, duplicatas, triados, excluídos, buscados, não obtidos, avaliados, excluídos na elegibilidade, pré-incluídos)."""
    sought = prisma.get("sought_for_retrieval", 0)
    return (
        prisma.get("identified_total", 0),
        prisma.get("duplicates_removed", 0),
        prisma.get("screened", 0),
        prisma.get("screening_excluded", 0),
        sought,
        prisma.get("not_retrieved", 0),
        prisma.get("assessed_for_eligibility", sought),
        prisma.get("eligibility_excluded", 0),
        prisma.get("preincluded_studies", sought),
    )


def _fill_template(template: str, prisma: dict) -> str:
    identified, duplicates, screened, excluded, sought, not_retrieved, assessed, eligibility_excluded, preincluded = _flow_numbers(prisma)
    # IDs dos elementos <text> do modelo -> novo conteúdo.
    replacements = {
        "text22": f"Databases (n = {identified})",
        "text23": "Registers (n = 0)",
        "text25": f"Duplicate records (n = {duplicates})",
        "text27": "tools (n = 0)",
        "text28": "Records removed for other reasons (n = 0)",
        "text30": f"(n = {screened})",
        "text32": f"(n = {excluded})",
        "text34": f"(n = {sought})",
        "text36": f"(n = {not_retrieved})",
        "text38": f"(n = {assessed})",
        "text47": f"(n = {preincluded})",
        "text49": f"(n = {preincluded})",
        "text52": "Websites (n = 0)",
        "text53": "Organisations (n = 0)",
        "text54": "Citation searching (n = 0)",
        "text56": "(n = 0)",
        "text58": "(n = 0)",
        "text60": "(n = 0)",
        "text62": "Reason 1 (n = 0)",
        "text63": "Reason 2 (n = 0)",
        "text64": "Reason 3 (n = 0)",
    }
    for text_id, value in replacements.items():
        pattern = rf'(<text\b(?=[^>]*\bid="{re.escape(text_id)}")[^>]*>).*?(</text>)'
        template = re.sub(pattern, lambda match: f"{match.group(1)}{escape(value)}{match.group(2)}", template, count=1, flags=re.DOTALL)
    return _fill_exclusion_box(template, _exclusion_lines(prisma, MAX_REASON_LINES))


def _exclusion_lines(prisma: dict, limit: int, width: int = 32) -> list[str]:
    """Uma linha por filtro não atendido ("Filtro (n = 10)"); o excedente de `limit` vira "Outros filtros". A soma dos n é preservada."""
    reasons = [(reason["label"], reason["n"]) for reason in prisma.get("exclusion_reasons", [])]
    if len(reasons) > limit:
        reasons = reasons[:limit - 1] + [("Outros filtros", sum(n for _, n in reasons[limit - 1:]))]
    shorten = lambda label: label if len(label) <= width else label[:width - 1].rstrip() + "…"
    return [f"{shorten(label)} (n = {n})" for label, n in reasons] or ["Nenhum registro excluído (n = 0)"]


def _fill_exclusion_box(template: str, lines: list[str]) -> str:
    """Reescreve a caixa "Reports excluded" do modelo, com uma linha por motivo e altura ajustada (centrada na seta)."""
    block = re.search(r'(<a\b[^>]*\bid="a45"[^>]*>)(.*?)(</a>)', template, flags=re.DOTALL)
    polygon = re.search(r'<polygon\b[^>]*\bid="polygon38"[^>]*?/>', block.group(2)) if block else None
    if not polygon:  # modelo sem a estrutura esperada: troca só os textos existentes
        for index, text_id in enumerate(f"text{number}" for number in range(40, 46)):
            value = lines[index] if index < len(lines) else ""
            template = re.sub(rf'(<text\b(?=[^>]*\bid="{text_id}")[^>]*>).*?(</text>)', lambda match: f"{match.group(1)}{escape(value)}{match.group(2)}", template, count=1, flags=re.DOTALL)
        return template
    step, padding_top, padding_bottom, center_y = 14.4, 14.7, 7.5, -225  # medidas do modelo (7 linhas = 108,6 de altura)
    height = step * len(lines) + padding_top + padding_bottom
    top = center_y - height / 2
    points = f"590.5,{top:.4f} 338.5,{top:.4f} 338.5,{top + height:.4f} 590.5,{top + height:.4f} 590.5,{top:.4f}"
    box = re.sub(r'points="[^"]*"', f'points="{points}"', polygon.group(0), count=1)
    texts = "".join(
        f'<text text-anchor="middle" x="464.5" y="{top + padding_top + index * step:.4f}" font-family="Helvetica,sans-Serif" font-size="12.00" fill="#000000">{escape(line)}</text>'
        for index, line in enumerate(["Reports excluded:", *lines])
    )
    return template[:block.start(2)] + box + texts + template[block.end(2):]


def _fallback_svg(prisma: dict) -> str:
    counts = prisma.get("repository_counts", {})

    def count(name: str) -> int:
        return int(counts.get(name, 0) or 0)

    identified, duplicates, screened, excluded, sought, not_retrieved, assessed, eligibility_excluded, preincluded = _flow_numbers(prisma)

    reason_lines = ["Relatórios excluídos:", *_exclusion_lines(prisma, MAX_REASON_LINES, width=36)]

    def box(x: int, y: int, width: int, height: int, lines: list[str], shade: str = "#ffffff") -> str:
        start = y + (height - (len(lines) * 22)) / 2 + 16
        text = "".join(f'<text x="{x + width / 2}" y="{start + index * 22}" class="box-text">{escape(line)}</text>' for index, line in enumerate(lines))
        return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="4" fill="{shade}" class="box"/>{text}'

    content = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1900" height="1280" viewBox="0 0 1900 1280">',
        '<style>.title{font:700 25px Arial,sans-serif;fill:#17241e}.subtitle{font:14px Arial,sans-serif;fill:#52635a}.stage{font:700 13px Arial,sans-serif;fill:#1f6a4d;letter-spacing:1.5px}.column-heading{text-anchor:middle;font:700 15px Arial,sans-serif;fill:#17241e}.box{stroke:#263a30;stroke-width:2}.box-text{text-anchor:middle;font:15px Arial,sans-serif;fill:#17241e}.arrow{stroke:#263a30;stroke-width:2.2;fill:none;marker-end:url(#arrow)}.note{font:13px Arial,sans-serif;fill:#52635a}.warning{font:700 13px Arial,sans-serif;fill:#8a5a00}</style>',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#263a30"/></marker></defs>',
        '<rect width="1900" height="1280" fill="#ffffff"/>',
        '<text x="70" y="48" class="title">Fluxograma PRISMA 2020 — pré-triagem automática</text>',
        '<text x="70" y="74" class="subtitle">Contagens preenchidas automaticamente a partir da pré-triagem.</text>',
        '<rect x="70" y="96" width="840" height="42" rx="18" fill="#ffc62a"/><text x="490" y="123" class="column-heading">Identificação de novos estudos via bases e registros</text>',
        '<rect x="1020" y="96" width="810" height="42" rx="18" fill="#dcdcdc"/><text x="1425" y="123" class="column-heading">Identificação de novos estudos por outros métodos</text>',
        '<text x="70" y="175" class="stage">IDENTIFICAÇÃO</text>',
        box(70, 195, 400, 165, ["Registros identificados em bases", f"Scopus (n = {count('Scopus')}) · IEEE Xplore (n = {count('IEEE Xplore')})", f"Web of Science (n = {count('Web of Science')})", f"Outras fontes (n = {count('Outras fontes')})", f"Total (n = {identified})"], "#fffdf6"),
        box(560, 195, 350, 145, ["Registros removidos antes da triagem", f"Duplicatas (n = {duplicates})", "Inelegíveis por automação (n = 0)", "Outros motivos (n = 0)"], "#fffdf6"),
        box(1020, 195, 400, 145, ["Registros identificados em:", "Websites (n = 0)", "Organizações (n = 0)", "Busca por citações (n = 0)"], "#eeeeee"),
        '<path d="M470 267 H550" class="arrow"/><path d="M270 360 V445" class="arrow"/><path d="M1220 340 V445" class="arrow"/>',
        '<text x="70" y="425" class="stage">TRIAGEM</text>',
        box(70, 465, 400, 84, ["Registros triados", f"(n = {screened})"]),
        box(560, 465, 350, 84, ["Registros excluídos", f"(n = {excluded})"], "#fff7f5"),
        box(1020, 465, 350, 84, ["Relatórios buscados para obtenção", "(n = 0)"], "#eeeeee"),
        box(1460, 465, 350, 84, ["Relatórios não obtidos", "(n = 0)"], "#eeeeee"),
        '<path d="M470 507 H550" class="arrow"/><path d="M1370 507 H1450" class="arrow"/><path d="M270 549 V635" class="arrow"/><path d="M1195 549 V635" class="arrow"/>',
        '<text x="70" y="615" class="stage">ELEGIBILIDADE</text>',
        box(70, 655, 400, 84, ["Relatórios buscados para obtenção", f"(n = {sought})"]),
        box(560, 655, 350, 84, ["Relatórios não obtidos", f"(n = {not_retrieved})"], "#fff7f5"),
        box(1020, 655, 350, 84, ["Relatórios avaliados para elegibilidade", "(n = 0)"], "#eeeeee"),
        box(1460, 620, 350, 155, ["Relatórios excluídos:", "Razão 1 (n = 0)", "Razão 2 (n = 0)", "Razão 3 (n = 0)"], "#eeeeee"),
        '<path d="M470 697 H550" class="arrow"/><path d="M1370 697 H1450" class="arrow"/><path d="M270 739 V825" class="arrow"/><path d="M1195 739 V825" class="arrow"/>',
        box(70, 845, 400, 84, ["Relatórios avaliados para elegibilidade", f"(n = {assessed})"]),
        box(560, round(887.5 - (22 * len(reason_lines) + 22) / 2), 350, 22 * len(reason_lines) + 22, reason_lines, "#fff7f5"),
        '<path d="M470 887 H550" class="arrow"/><path d="M270 929 V1055" class="arrow"/><path d="M1195 739 V1098 H480" class="arrow"/>',
        '<text x="70" y="1035" class="stage">INCLUÍDOS</text>',
        box(70, 1075, 400, 96, ["Estudos incluídos na revisão", f"Pré-inclusões automáticas (n = {preincluded})"], "#f4f8f5"),
        '<text x="70" y="1220" class="note">Gerado pela ferramenta de triagem. O ramo de outros métodos inicia em zero até que essas fontes sejam registradas.</text>',
        '<text x="70" y="1248" class="warning">OBSERVAÇÃO: a análise criteriosa humana do texto completo é indispensável para confirmar elegibilidade e inclusão final.</text>',
        '</svg>',
    ]
    return "".join(content)
