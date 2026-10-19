"""Etapa 5 de 5 · Servidor: filtros da última sessão, API JSON e interface (biblioteca padrão).

Sequência do programa: base -> input -> analisys -> output -> server.
Cada etapa só importa das anteriores.
"""

import json
import os
import struct
import tempfile
import threading
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

from .base import (
    DATA_DIR,
    display_score,
    EXCLUDED,
    FRONTEND_DIR,
    HEALTH_TOKEN,
    INCLUDED,
    LAST_SESSION_FILE,
    MAX_UPLOAD_BYTES,
    source_fingerprint,
    Upload,
)
from .input import ALLOWED_EXTENSIONS, FORMAT_NAMES, read_records, to_ris
from .analisys import Filter, parse_filter_configuration, read_filter_configuration, screen_files
from .output import build_excel, build_prisma_excel, build_prisma_svg, build_ris


# ============================================================================
# Filtros da última sessão (cache/last_session.json)
# ============================================================================

_lock = threading.Lock()


def _editable(filters: list[Filter]) -> list[dict]:
    """Só os campos que a tela edita (sem os campos internos usados na avaliação)."""
    return [{key: rule[key] for key in ("label", "terms", "weight", "required")} for rule in filters]


def save_last_session(filters: list[Filter], threshold: float) -> bool:
    """Substitui a sessão guardada. Devolve False se o disco não permitir; a análise não depende disso."""
    payload = {
        "filters": _editable(filters),
        "threshold": threshold,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            # Grava em arquivo temporário e troca de uma vez: uma queda no meio não corrompe a sessão guardada.
            descriptor, temporary = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, LAST_SESSION_FILE)
            return True
        except OSError:
            return False


def load_last_session() -> dict | None:
    """Devolve {"filters": [...], "threshold": n} da última sessão, ou None se não houver uma válida."""
    with _lock:
        try:
            raw = LAST_SESSION_FILE.read_text(encoding="utf-8")
        except OSError:
            return None
    filters, threshold = read_filter_configuration(raw)  # a mesma validação dos filtros recebidos da tela
    if not filters:
        return None
    return {"filters": _editable(filters), "threshold": threshold}


# ============================================================================
# Servidor HTTP local e API JSON
# ============================================================================

HOST = "127.0.0.1"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}  # recusa outros nomes (proteção contra DNS rebinding)
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}

# tipo de exportação -> (campos JSON esperados, gerador, nome do arquivo, mimetype)
EXPORTS = {
    "excel": ({"records": list}, lambda d: build_excel(d["records"]), "triagem_artigos.xlsx", XLSX_MIMETYPE),
    "ris": ({"records": list}, lambda d: build_ris(d["records"]), "triagem_incluidos.ris", "application/x-research-info-systems"),
    "prisma": ({"records": list, "duplicates": list, "prisma": dict}, lambda d: build_prisma_excel(d["records"], d["duplicates"], d["prisma"]), "modelo_prisma_triagem.xlsx", XLSX_MIMETYPE),
    "prisma-svg": ({"prisma": dict}, lambda d: build_prisma_svg(d["prisma"]), "fluxograma_prisma_triagem.svg", "image/svg+xml"),
}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


# ------------------------------------------------------------------- análise


def parse_analysis_request(body: bytes) -> tuple[list[Upload], dict]:
    """Corpo: 4 bytes (tamanho N) + N bytes de JSON {filters, threshold, files:[{name,size}]} + conteúdo dos arquivos em sequência."""
    try:
        (meta_size,) = struct.unpack(">I", body[:4])
        meta = json.loads(body[4:4 + meta_size])
        offset, uploads = 4 + meta_size, []
        for item in meta["files"]:
            size = int(item["size"])
            if size < 0 or offset + size > len(body):
                raise ValueError("arquivo truncado")
            uploads.append(Upload(str(item["name"]), body[offset:offset + size]))
            offset += size
        if offset != len(body) or not isinstance(meta, dict):
            raise ValueError("corpo com sobra")
    except (struct.error, ValueError, KeyError, TypeError):
        raise ApiError("Não foi possível ler os dados enviados.") from None
    return uploads, meta


def checked_uploads(uploads: list[Upload]) -> list[Upload]:
    uploads = [upload for upload in uploads if upload.filename]
    if not uploads:
        raise ApiError(f"Envie pelo menos um arquivo ({FORMAT_NAMES}).")
    invalid = [upload.filename for upload in uploads if not upload.filename.lower().endswith(ALLOWED_EXTENSIONS)]
    if invalid:
        raise ApiError(f"Formato não aceito: {', '.join(invalid)}. Use {FORMAT_NAMES}.")
    return uploads


def convert(body: bytes) -> tuple[bytes, dict]:
    """Converte todos os arquivos enviados para um único RIS. Arquivos sem registros viram avisos."""
    uploads, _ = parse_analysis_request(body)
    records, warnings = [], []
    for upload in checked_uploads(uploads):
        found, _, error = read_records(upload)
        records += found
        if error:
            warnings.append(f"{upload.filename}: {error}")
    if not records:
        raise ApiError("Nenhum registro pôde ser convertido. " + " ".join(warnings))
    return to_ris(records).encode("utf-8"), {"X-Registros": str(len(records)), "X-Avisos": quote(" | ".join(warnings))}


def analyse(body: bytes) -> dict:
    uploads, meta = parse_analysis_request(body)
    uploads = checked_uploads(uploads)
    filters, threshold = parse_filter_configuration(meta)
    if not filters:
        raise ApiError("Adicione pelo menos um filtro com termos e peso antes de analisar.")

    save_last_session(filters, threshold)  # substitui a sessão anterior
    result = screen_files(uploads, filters, threshold)
    return present_results(result, threshold, sum(rule["weight"] for rule in filters))


def present_results(result, threshold: float, maximum_score: float) -> dict:
    """Resultados em JSON, já com os números formatados (o front-end só exibe)."""
    articles = []
    for article in result.articles:
        data = asdict(article)
        data["score_label"] = f"{display_score(article.relevance_score)}/{display_score(article.maximum_score)}"
        for check in data["filter_results"]:
            check["points_label"], check["weight_label"] = display_score(check["points"]), display_score(check["weight"])
        articles.append(data)
    return {
        "articles": articles,
        "duplicates": [asdict(article) for article in result.duplicates],
        "prisma": result.prisma,
        "included": sum(article.decision == INCLUDED for article in result.articles),
        "excluded": sum(article.decision == EXCLUDED for article in result.articles),
        "ris_included": sum(article.decision == INCLUDED and bool(article.ris_record) for article in result.articles),
        "threshold_label": display_score(threshold),
        "maximum_label": display_score(maximum_score),
    }


def export(kind: str, body: bytes) -> tuple[bytes, str, str]:
    fields, build, filename, mimetype = EXPORTS[kind]
    try:
        data = json.loads(body)
        valid = isinstance(data, dict) and all(isinstance(data.get(name), expected) for name, expected in fields.items())
    except ValueError:
        valid = False
    if not valid:
        raise ApiError("Não foi possível preparar o arquivo para exportação.")
    return build(data).getvalue(), filename, mimetype


# ------------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Triagem"
    health_body = ""  # preenchido em serve()

    def log_message(self, *_args) -> None:  # sem registro de requisições (o console pode nem existir)
        pass

    # --- respostas
    def _send(self, status: int, body: bytes = b"", content_type: str = "application/json; charset=utf-8", headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _error(self, error: ApiError) -> None:
        self._json({"error": error.message}, error.status)

    # --- entrada
    def _host_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").rpartition(":")[0] or (self.headers.get("Host") or "")
        return host in LOCAL_HOSTS

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", ""))
            if length < 0:
                raise ValueError
        except ValueError:
            self.close_connection = True
            raise ApiError("Tamanho da requisição não informado.", 411) from None
        if length > MAX_UPLOAD_BYTES:
            self._discard(length)  # lê e descarta, para o navegador receber a resposta em vez de ver a conexão cair
            raise ApiError("O envio excede o limite total de 32 MB.", 413)
        return self.rfile.read(length)

    def _discard(self, length: int) -> None:
        self.close_connection = True
        remaining = min(length, 8 * MAX_UPLOAD_BYTES)  # acima disso, apenas fecha a conexão
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 1 << 20))
            if not chunk:
                break
            remaining -= len(chunk)

    # --- rotas
    def do_GET(self) -> None:
        try:
            if not self._host_allowed():
                raise ApiError("Acesso recusado.", 403)
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._send(200, self.health_body.encode(), "text/plain; charset=utf-8")
            elif path == "/api/last-session":
                saved = load_last_session()
                self._json(saved) if saved else self._send(204)
            elif path == "/" or path.startswith("/static/"):
                self._static("index.html" if path == "/" else path.removeprefix("/static/"))
            else:
                raise ApiError("Página não encontrada.", 404)
        except ApiError as error:
            self._error(error)

    do_HEAD = do_GET

    def _static(self, name: str) -> None:
        file = FRONTEND_DIR / name
        if "/" in name or "\\" in name or not file.is_file():  # só os arquivos diretamente dentro de interface/
            raise ApiError("Arquivo não encontrado.", 404)
        self._send(200, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

    def do_POST(self) -> None:
        try:
            if not self._host_allowed():
                self.close_connection = True
                raise ApiError("Acesso recusado.", 403)
            path = self.path.split("?", 1)[0]
            body = self._read_body()  # sempre consome o corpo, para manter a conexão utilizável
            if path == "/api/analyse":
                self._json(analyse(body))
            elif path == "/api/convert":
                content, headers = convert(body)
                self._send(200, content, "application/x-research-info-systems", {**headers, "Content-Disposition": 'attachment; filename="referencias_convertidas.ris"'})
            elif path.startswith("/api/export/") and path.removeprefix("/api/export/") in EXPORTS:
                content, filename, mimetype = export(path.removeprefix("/api/export/"), body)
                self._send(200, content, mimetype, {"Content-Disposition": f'attachment; filename="{filename}"'})
            else:
                raise ApiError("Página não encontrada.", 404)
        except ApiError as error:
            self._error(error)
        except Exception as error:  # falha inesperada: a tela mostra uma mensagem (nada é gravado em arquivo)
            self._error(ApiError(f"Erro inesperado ao processar a requisição ({type(error).__name__}).", 500))


class LocalServer(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR permitiria abrir uma segunda instância na mesma porta; nos demais sistemas ele só evita o TIME_WAIT.
    allow_reuse_address = os.name != "nt"


def make_server(port: int) -> LocalServer:
    """Cria o servidor já ligado à porta (levanta OSError se ela estiver ocupada)."""
    Handler.health_body = f"{HEALTH_TOKEN}:{source_fingerprint()}"  # calculado ao iniciar: reflete o código carregado
    return LocalServer((HOST, port), Handler)


def serve(port: int) -> None:
    """Executa o servidor até ser interrompido (Ctrl+C)."""
    with make_server(port) as server:
        server.serve_forever()
