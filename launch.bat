@echo off
setlocal EnableExtensions

rem Duplo clique: usa o Python do sistema (3.10 ou superior), inicia o servidor local e abre o navegador.
rem Nao ha nada a instalar: a aplicacao usa so a biblioteca padrao do Python.
cd /d "%~dp0"
title Triagem de artigos

echo.
echo ==========================================
echo   Triagem de artigos - inicializacao
echo ==========================================
echo.

rem 1. Procura o Python 3.10 ou superior ja instalado.
set "PY="
for %%C in ("py -3" "python") do if not defined PY %%~C -c "import sys;sys.exit(sys.version_info<(3,10))" >nul 2>&1 && set "PY=%%~C"
if not defined PY (
    echo ERRO: Python 3.10 ou superior nao foi encontrado.
    echo Instale o Python e marque a opcao "Add Python to PATH".
    pause
    exit /b 1
)
echo [1/2] Python encontrado: %PY%

rem 2. Executa o inicializador (codigo Python no fim deste arquivo) e o servidor NESTE console,
rem    que fica aberto (minimizado) enquanto o site estiver em uso.
rem    Para desligar o servidor: volte a esta janela, pressione Ctrl+C e responda S.
echo [2/2] Iniciando o servidor e abrindo o navegador...
set "TRIAGEM_ROOT=%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
%PY% -c "import sys;exec(compile(open(sys.argv[1],encoding='utf-8').read().split('\n#PYTHON-INICIO\n',1)[1],'launch.bat','exec'))" "%~f0"
if errorlevel 1 goto START_FAILED
exit /b 0

:START_FAILED
echo.
echo ERRO: o servidor local nao iniciou. Veja a mensagem acima.
pause
exit /b 1

rem ---------------------------------------------------------------------------
rem Daqui para baixo e Python (o cmd nunca chega aqui: os comandos acima terminam com exit).
rem ---------------------------------------------------------------------------
#PYTHON-INICIO
# Inicializador da aplicação local (só biblioteca padrão do Python; não há nada a instalar). Roda embutido no launch.bat.
# O servidor roda no console do .bat, que fica aberto (minimizado): para desligar, Ctrl+C nele (responda S).
# Se já existe um servidor atualizado em outra janela, apenas abre o navegador; se a porta padrão estiver
# ocupada ou rodar código antigo, usa outra porta livre. Nenhum arquivo de relatório é gerado.
import os
import socket
import sys
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("TRIAGEM_PORT", "5000"))
HEALTH_PATH = "/healthz"

ROOT = Path(os.environ["TRIAGEM_ROOT"])  # definida pelo .bat
sys.path.insert(0, str(ROOT))
from scripts.base import HEALTH_TOKEN, source_fingerprint  # só biblioteca padrão
# O health check é sempre local: ignora o proxy do sistema, que o faria falhar.
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ------------------------------------------------------------------- mensagens e erros


def say(message: str) -> None:
    if sys.stdout:
        print(message, flush=True)


def show_error(message: str) -> None:
    """Mostra a falha no console e numa caixa de mensagem (não depende de tkinter)."""
    if sys.stderr:
        print(f"ERRO: {message}", file=sys.stderr, flush=True)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "Triagem de artigos", 0x10)  # MB_ICONERROR
    except Exception:
        pass  # fora do Windows ou sem interface gráfica: a mensagem já foi para o console


def minimize_console() -> None:
    """Deixa o console minimizado (sem tirar o foco do navegador); ele segue aberto para o Ctrl+C."""
    try:
        import ctypes

        window = ctypes.windll.kernel32.GetConsoleWindow()
        if window:
            ctypes.windll.user32.ShowWindow(window, 7)  # SW_SHOWMINNOACTIVE
    except Exception:
        pass


# ------------------------------------------------------------------- servidor


def url_for(port: int) -> str:
    return f"http://{HOST}:{port}"


def expected_health() -> str:
    """Resposta que um servidor iniciado com os arquivos atuais dá em /healthz."""
    return f"{HEALTH_TOKEN}:{source_fingerprint()}"


def read_health(port: int) -> str | None:
    """Resposta de /healthz, ou None se não houver servidor desta aplicação na porta."""
    try:
        with LOCAL_OPENER.open(f"{url_for(port)}{HEALTH_PATH}", timeout=0.5) as response:
            body = response.read().decode("utf-8", errors="replace")
            return body if response.status == 200 and body.startswith(HEALTH_TOKEN) else None
    except (OSError, urllib.error.URLError):
        return None


def port_is_free(port: int) -> bool:
    """Testa a porta sem SO_REUSEADDR: no Windows ele permitiria "roubar" uma porta já em uso."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def choose_port() -> int:
    """Usa a porta padrão se estiver livre; caso contrário, pede uma porta livre ao sistema."""
    if port_is_free(DEFAULT_PORT):
        return DEFAULT_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def launch() -> int:
    """Garante um servidor ativo e abre o navegador. Retorna 0 se deu certo."""
    expected = expected_health()
    running = read_health(DEFAULT_PORT)
    if running == expected:
        say(f"A aplicação já está ativa em outra janela ({url_for(DEFAULT_PORT)}); abrindo o navegador.")
        webbrowser.open(url_for(DEFAULT_PORT), new=2)
        return 0
    if running is not None:
        say(f"O servidor da porta {DEFAULT_PORT} roda uma versão desatualizada do código; iniciando um novo em outra porta.")

    from scripts.server import make_server

    try:
        server = make_server(choose_port())
    except OSError as error:
        show_error(f"Não foi possível iniciar o servidor local.\n\nDetalhe: {error}")
        return 1

    url = url_for(server.server_address[1])
    with server:
        say(f"Servidor ativo em {url}")
        say("Para DESLIGAR o servidor: volte a esta janela e pressione Ctrl+C (responda S se o Windows perguntar).")
        webbrowser.open(url, new=2)  # a conexão fica na fila até o servidor começar a atender
        minimize_console()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            say("Servidor encerrado.")
    return 0


def main() -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # consoles antigos (cp850) não devem derrubar a mensagem
    try:
        return launch()
    except KeyboardInterrupt:
        return 0
    except Exception as error:  # nada deve falhar em silêncio
        show_error(f"Erro inesperado ao iniciar: {error}\n\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
