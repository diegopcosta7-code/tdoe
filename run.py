#!/usr/bin/env python3
"""
TdoE — Tabuleiro do Empreendedor
Servidor de desenvolvimento local.

Uso:
    python run.py              # porta padrão 8000
    python run.py --port 5000  # porta personalizada
    python run.py --no-browser # sem abrir navegador automaticamente
"""

import argparse
import os
import sys
import time
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# ─── Cores no terminal ────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def banner():
    print(f"""
{CYAN}{BOLD}┌─────────────────────────────────────────┐
│  TdoE — Tabuleiro do Empreendedor  🎲   │
│  UFLA · Daniela Meirelles & Diego Costa │
└─────────────────────────────────────────┘{RESET}
""")


# ─── Handler silencioso (sem log de cada request) ─────────────────────────────
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suprime logs de acesso

    def end_headers(self):
        # Cabeçalhos para evitar cache durante desenvolvimento
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


# ─── Abrir navegador após breve delay ────────────────────────────────────────
def abrir_navegador(url: str, delay: float = 0.8):
    def _open():
        time.sleep(delay)
        webbrowser.open(url)
    t = threading.Thread(target=_open, daemon=True)
    t.start()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Servidor local do TdoE")
    parser.add_argument("--port", type=int, default=8000,
                        help="Porta HTTP (padrão: 8000)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Não abrir o navegador automaticamente")
    args = parser.parse_args()

    # Garante que o servidor sirva a partir do diretório deste script
    base_dir = Path(__file__).parent.resolve()
    os.chdir(base_dir)

    # Verifica se o frontend existe
    frontend = base_dir / "tdoe_frontend.html"
    if not frontend.exists():
        print(f"  ❌  Arquivo não encontrado: {frontend}")
        sys.exit(1)

    url = f"http://localhost:{args.port}/tdoe_frontend.html"

    try:
        server = HTTPServer(("", args.port), QuietHandler)
    except OSError:
        print(f"  ❌  Porta {args.port} já está em uso.")
        print(f"       Tente: python run.py --port 8080")
        sys.exit(1)

    banner()
    print(f"  {GREEN}✓{RESET}  Servidor rodando em {CYAN}{BOLD}{url}{RESET}")
    print(f"  {YELLOW}⚡{RESET}  Pressione Ctrl+C para encerrar\n")

    if not args.no_browser:
        abrir_navegador(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}⏹{RESET}  Servidor encerrado.")


if __name__ == "__main__":
    main()
