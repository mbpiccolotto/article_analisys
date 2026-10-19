"""Etapa 3 de 5 · Triagem: filtros, pontuação, deduplicação e contagens do fluxo PRISMA.

Sequência do programa: base -> input -> analisys -> output -> server.
Cada etapa só importa das anteriores.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .base import (
    Article,
    display_score,
    EXCLUDED,
    INCLUDED,
    MAX_FILTERS,
    MAX_TERMS_PER_FILTER,
    MAX_TEXT_LENGTH,
    MAX_WEIGHT,
    normalize,
    NOT_IDENTIFIED,
    parse_decimal,
    secure_filename,
    text_key,
    UNTITLED_RECORD,
    Upload,
)
from .input import detect_repository, find_doi, find_year, format_ris, read_records, ris_value


# ============================================================================
# Filtros: validação e avaliação dos critérios de triagem
# ============================================================================

Filter = dict[str, Any]


def _clean_filter(item: Any, position: int) -> Filter | None:
    """Valida um filtro; devolve None quando está incompleto ou malformado."""
    if not isinstance(item, dict):
        return None
    raw_terms = item.get("terms", [])
    if isinstance(raw_terms, str):
        raw_terms = re.split(r"[\n;,]", raw_terms)
    if not isinstance(raw_terms, list):
        return None
    label = normalize(str(item.get("label", "")))[:MAX_TEXT_LENGTH]
    terms = [normalize(str(term))[:MAX_TEXT_LENGTH] for term in raw_terms if normalize(str(term))][:MAX_TERMS_PER_FILTER]
    try:
        weight = max(0, min(parse_decimal(item.get("weight", 0)), MAX_WEIGHT))
    except (TypeError, ValueError):
        weight = 0
    if not (label and terms and weight > 0):
        return None
    return {
        "id": f"filter_{position}",
        "label": label,
        "terms": terms,
        "keys": [text_key(term) for term in terms],  # pré-normalizados: evita refazer por artigo
        "weight": weight,
        "required": bool(item.get("required", False)),
    }


def read_filter_configuration(raw: str | None) -> tuple[list[Filter], float]:
    """Lê a configuração em JSON (texto). Em caso de erro, devolve ([], 0)."""
    try:
        return parse_filter_configuration(json.loads(raw) if raw else {})
    except ValueError:
        return [], 0


def parse_filter_configuration(data: Any) -> tuple[list[Filter], float]:
    """Valida {"filters": [...], "threshold": n}. Em caso de erro, devolve ([], 0)."""
    try:
        incoming = data.get("filters", [])
        threshold = parse_decimal(data.get("threshold", 0))
    except (AttributeError, TypeError, ValueError):
        return [], 0

    if not isinstance(incoming, list):
        return [], 0
    filters = [f for position, item in enumerate(incoming[:MAX_FILTERS], start=1) if (f := _clean_filter(item, position))]
    return filters, max(0, min(threshold, sum(f["weight"] for f in filters)))


def evaluate_filters(article: Article, study_text: str, filters: list[Filter], threshold: float) -> None:
    """Pontua o artigo pelos filtros e decide inclusão (limiar + filtros obrigatórios)."""
    searchable_text = text_key(study_text)
    results = []
    for rule in filters:
        matched_terms = [term for term, key in zip(rule["terms"], rule["keys"]) if key in searchable_text]
        passed = bool(matched_terms)
        results.append({"label": rule["label"], "weight": rule["weight"], "required": rule["required"], "matched": passed, "matched_terms": matched_terms, "points": rule["weight"] if passed else 0})
        (article.criteria_met if passed else article.criteria_missing).append(f"{rule['label']} ({display_score(rule['weight'])} pt)")

    article.filter_results = results
    article.maximum_score = sum(rule["weight"] for rule in filters)
    article.relevance_score = sum(result["points"] for result in results)
    unmet_required = [result["label"] for result in results if result["required"] and not result["matched"]]

    if article.relevance_score >= threshold and not unmet_required:
        article.decision = INCLUDED
        article.rationale = f"Atende ao limiar de {display_score(threshold)} ponto(s) e aos filtros obrigatórios."
        article.exclusion_reason = article.exclusion_group = ""
        return

    reasons = [f"Filtro obrigatório não identificado: {label}" for label in unmet_required]
    if article.relevance_score < threshold:
        reasons.append(f"Pontuação abaixo do limiar ({display_score(article.relevance_score)}/{display_score(threshold)})")
    article.decision = EXCLUDED
    article.exclusion_group = _exclusion_group(results)
    article.exclusion_reason = "; ".join(reasons) or "Não atendeu aos filtros configurados"
    article.rationale = article.exclusion_reason


def _exclusion_group(results: list[dict[str, Any]]) -> str:
    """Filtro que não foi atendido e serve de grupo PRISMA: o primeiro obrigatório; sem obrigatório, o de maior peso."""
    missing = [result for result in results if not result["matched"]]
    required = [result for result in missing if result["required"]]
    chosen = required[0] if required else max(missing, key=lambda result: result["weight"], default=None)  # max devolve o primeiro em empate
    return chosen["label"] if chosen else "Pontuação abaixo do limiar"


# ============================================================================
# Pré-triagem: uploads em artigos avaliados, deduplicação e contagens PRISMA
# ============================================================================

@dataclass
class ScreeningResult:
    articles: list[Article]
    duplicates: list[Article]
    prisma: dict[str, Any]


def screen_files(files: list[Upload], filters: list[Filter], threshold: float) -> ScreeningResult:
    """Analisa todos os arquivos enviados e devolve artigos únicos, duplicatas e contagens PRISMA."""
    analysed = [article for file in files for article in analyse_upload(file, filters, threshold)]
    repository_counts = Counter(article.repository for article in analysed)  # antes da deduplicação
    articles, duplicates = deduplicate_articles(analysed)
    return ScreeningResult(articles, duplicates, build_counts(repository_counts, len(analysed), len(duplicates), articles))


def analyse_upload(upload: Upload, filters: list[Filter], threshold: float) -> list[Article]:
    records, kind, error = read_records(upload)
    if error:
        return [_rejected_file(upload.filename, error)]
    return [_analyse_record(record, upload.filename, kind, position, filters, threshold) for position, record in enumerate(records, start=1)]


def _rejected_file(filename: str, message: str) -> Article:
    article = Article(filename=secure_filename(filename or "referencias.ris"), extraction_note=message, repository=detect_repository(filename))
    article.decision, article.rationale, article.exclusion_reason, article.exclusion_group = "Rejeitado (arquivo inválido)", message, message, "Arquivo inválido"
    return article


def _analyse_record(record: dict[str, list[str]], source_name: str, kind: str, position: int, filters: list[Filter], threshold: float) -> Article:
    title = ris_value(record, "TI", "T1", "CT") or UNTITLED_RECORD
    abstract = ris_value(record, "AB", "N2") or "Não informado no registro"
    authors = "; ".join(normalize(value) for value in record.get("AU", record.get("A1", [])) if normalize(value)) or "Não identificado automaticamente"
    journal = ris_value(record, "JO", "JF", "T2") or "A preencher na revisão integral"
    keywords = " ".join(normalize(value) for value in record.get("KW", []) if normalize(value))
    doi = ris_value(record, "DO") or find_doi(ris_value(record, "UR")) or ""
    article = Article(
        filename=f"{secure_filename(source_name or 'referencias.ris')} — registro {position}",
        source_type=kind,
        title=title,
        year=find_year(ris_value(record, "PY", "Y1", "DA")) or NOT_IDENTIFIED,
        doi=doi or NOT_IDENTIFIED,
        abstract=abstract,
        authors=authors,
        journal=journal,
        extraction_note="Triagem baseada nos metadados do registro (título, resumo, palavras-chave e periódico). Confirme no texto completo.",
        repository=detect_repository(source_name, record),
        ris_record=format_ris(record),
    )
    evaluate_filters(article, "\n".join(value for value in (title, abstract, keywords, journal) if value), filters, threshold)
    return article


# ------------------------------------------------------------------ deduplicação


def _duplicate_key(article: Article) -> tuple[str, str] | None:
    """Chave de deduplicação: DOI normalizado (prioridade) ou título normalizado."""
    doi = article.doi if article.doi != NOT_IDENTIFIED else ""
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    doi = re.sub(r"[^a-z0-9._;()/:-]", "", doi.lower())
    if doi.startswith("10.") and "/" in doi:
        return "DOI", doi
    title = re.sub(r"[^a-z0-9]", "", text_key(article.title))
    if len(title) >= 12 and article.title != UNTITLED_RECORD:
        return "Título normalizado", title
    return None


def deduplicate_articles(articles: list[Article]) -> tuple[list[Article], list[Article]]:
    """Mantém o primeiro registro de cada chave; devolve (únicos, duplicatas) para auditoria."""
    unique: list[Article] = []
    duplicates: list[Article] = []
    seen: dict[tuple[str, str], Article] = {}
    for article in articles:
        key = _duplicate_key(article)
        original = seen.get(key) if key else None
        if original is None:
            unique.append(article)
            if key:
                seen[key] = article
            continue
        article.duplicate_of = original.title
        article.duplicate_reason = f"{key[0]} equivalente"
        repositories = [item.strip() for item in original.repository.split(" · ") if item.strip()]
        if article.repository not in repositories:
            original.repository = " · ".join([*repositories, article.repository])
        duplicates.append(article)
    return unique, duplicates


def build_counts(repository_counts: Counter, identified_total: int, duplicates_removed: int, articles: list) -> dict:
    """Contagens do fluxo PRISMA, calculadas a partir dos artigos já deduplicados."""
    included = sum(article.decision == INCLUDED for article in articles)
    # Cada excluído entra em um único grupo (o filtro não atendido), então a soma dos n é igual a screening_excluded.
    groups = Counter(article.exclusion_group or "Outros motivos" for article in articles if article.decision != INCLUDED)
    return {
        "repository_counts": dict(repository_counts),
        "identified_total": identified_total,
        "duplicates_removed": duplicates_removed,
        "screened": len(articles),
        "screening_excluded": len(articles) - included,
        "exclusion_reasons": [{"label": label, "n": n} for label, n in groups.most_common()],  # maior n primeiro; empate na ordem de aparição
        "sought_for_retrieval": included,
        "not_retrieved": 0,
        "assessed_for_eligibility": included,
        "eligibility_excluded": 0,
        "preincluded_studies": included,
    }
