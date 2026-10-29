"""
TdoE — Tabuleiro do Empreendedor · API v1.3.0
==============================================
Back-end FastAPI · persistência via Supabase · compatível com Render.com

COMO RODAR LOCALMENTE
---------------------
    pip install fastapi uvicorn python-jose python-multipart supabase
    python tdoe_app.py

Variáveis de ambiente necessárias (Render → Environment):
    SUPABASE_URL  = https://xxxx.supabase.co
    SUPABASE_KEY  = eyJ...  (anon/public key)
"""

# ─────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────
import uuid
import socket
import hashlib
import hmac
import random
import string
import os
from datetime import datetime, timedelta
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jose import jwt, JWTError
from supabase import create_client, Client


# ─────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────
SECRET_KEY  = "tdoe-chave-secreta-2025-ufla"
ALGORITHM   = "HS256"
TOKEN_HORAS = 8

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://jvkgkmkuptioksmsurrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp2a2drbWt1cHRpb2tzbXN1cnJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI1OTg1NzksImV4cCI6MjEwODE3NDU3OX0.b9l_MMjTBLd2XMIK4DAfSGwlDftWTjnfcMUyZEh9-Yc")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FASES_POR_CHAVE = {
    "problema":      ["Contexto", "Características", "Motivação"],
    "solucao":       ["Características", "Custos", "Riscos"],
    "parcerias":     ["Recursos", "Características", "Tempo"],
    "oportunidades": ["Características", "Diferenciação", "Aplicabilidade"],
}
CHAVES_LIVRES = {"solucao", "parcerias", "oportunidades"}


# ─────────────────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────────────────
def uid() -> str:
    return str(uuid.uuid4())

def agora() -> str:
    return datetime.utcnow().isoformat()

def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()

def verificar_senha(senha: str, hash_: str) -> bool:
    return hmac.compare_digest(hash_senha(senha), hash_)

def criar_token(dados: dict) -> str:
    payload = dados.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_HORAS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decodificar_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

def gerar_codigo() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def porta_livre(inicio: int = 8000) -> int:
    for p in range(inicio, inicio + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return inicio


# ─────────────────────────────────────────────────────────
# HELPERS SUPABASE
# ─────────────────────────────────────────────────────────
def db_get(tabela: str, id: str) -> Optional[dict]:
    res = supabase.table(tabela).select("*").eq("id", id).execute()
    return res.data[0] if res.data else None

def db_list(tabela: str, filtros: dict = {}) -> list:
    q = supabase.table(tabela).select("*")
    for k, v in filtros.items():
        q = q.eq(k, v)
    return q.execute().data or []

def db_insert(tabela: str, dados: dict) -> dict:
    res = supabase.table(tabela).insert(dados).execute()
    return res.data[0]

def db_update(tabela: str, id: str, dados: dict) -> dict:
    res = supabase.table(tabela).update(dados).eq("id", id).execute()
    return res.data[0] if res.data else {}

def db_find_one(tabela: str, filtros: dict) -> Optional[dict]:
    items = db_list(tabela, filtros)
    return items[0] if items else None


# ─────────────────────────────────────────────────────────
# SEGURANÇA
# ─────────────────────────────────────────────────────────
bearer = HTTPBearer(auto_error=False)

def get_usuario_atual(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
):
    if not credentials:
        raise HTTPException(401, "Token não informado.")
    payload = decodificar_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Token inválido ou expirado.")
    return payload

def get_educador(payload=Depends(get_usuario_atual)):
    if payload.get("perfil") not in ("educador", "instituicao"):
        raise HTTPException(403, "Apenas educadores têm acesso.")
    usuario = db_get("usuarios", payload["sub"])
    if not usuario:
        raise HTTPException(401, "Usuário não encontrado.")
    return usuario


# ─────────────────────────────────────────────────────────
# LÓGICA PEDAGÓGICA
# ─────────────────────────────────────────────────────────
def _inicializar_progressos(equipe_id: str):
    for chave, fases_nomes in FASES_POR_CHAVE.items():
        pid = uid()
        db_insert("progresso_chaves", {
            "id": pid, "equipe_id": equipe_id, "chave": chave,
            "status": "nao_iniciada",
            "iniciada_em": None, "concluida_em": None,
            "ultima_atividade_em": None,
        })
        for i, nome in enumerate(fases_nomes, 1):
            fid = uid()
            status = "disponivel" if chave == "problema" and i == 1 else "bloqueada"
            db_insert("progresso_fases", {
                "id": fid, "progresso_chave_id": pid,
                "numero_fase": i, "nome_fase": nome,
                "status": status, "conteudo": None, "concluida_em": None,
            })

def _progresso(equipe_id: str, chave: str) -> Optional[dict]:
    return db_find_one("progresso_chaves", {"equipe_id": equipe_id, "chave": chave})

def _fases(progresso_id: str) -> list:
    fases = db_list("progresso_fases", {"progresso_chave_id": progresso_id})
    return sorted(fases, key=lambda f: f["numero_fase"])

def _liberar_chaves_livres(equipe_id: str):
    for chave in CHAVES_LIVRES:
        prog = _progresso(equipe_id, chave)
        if prog and prog["status"] == "nao_iniciada":
            fases = _fases(prog["id"])
            if fases and fases[0]["status"] == "bloqueada":
                db_update("progresso_fases", fases[0]["id"], {"status": "disponivel"})

def resumo_chaves(equipe_id: str) -> dict:
    resultado = {}
    for chave in FASES_POR_CHAVE:
        prog = _progresso(equipe_id, chave)
        fases = _fases(prog["id"]) if prog else []
        status = prog["status"] if prog else "nao_iniciada"
        if status == "nao_iniciada" and fases and fases[0]["status"] == "disponivel":
            status = "disponivel"
        resultado[chave] = {
            "status": status,
            "fases": [
                {"numero": f["numero_fase"], "nome": f["nome_fase"],
                 "status": f["status"], "conteudo": f["conteudo"]}
                for f in fases
            ],
        }
    return resultado


# ─────────────────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────────────────
class UsuarioCriar(BaseModel):
    nome: str
    sobrenome: str
    email: str
    senha: str
    instituicao: Optional[str] = None

class LoginEntrada(BaseModel):
    email: str
    senha: str

class SessaoCriar(BaseModel):
    titulo: str
    contexto: str = "escolar"
    cenario: Optional[str] = None
    num_equipes: int = 5

class EntrarComCodigo(BaseModel):
    codigo: str
    nome: str
    numero_equipe: int

class AtivarChave(BaseModel):
    chave: str

class ConcluirFase(BaseModel):
    chave: str
    numero_fase: int
    conteudo: Optional[str] = ""

class SessaoAcao(BaseModel):
    acao: str

class CutucarEntrada(BaseModel):
    equipe_id: str
    de_participante_id: str
    para_participante_id: str

class SussurroEntrada(BaseModel):
    equipe_id: str
    de_participante_id: str
    para_participante_id: str
    mensagem: str

class BalaoColetivo(BaseModel):
    equipe_id: str
    participante_id: str
    mensagem: str

class PapelRPGEntrada(BaseModel):
    participante_id: str
    papel_id: str
    papel_nome: str
    papel_icone: str
    papel_cor: str


# ─────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title="TdoE — Tabuleiro do Empreendedor",
    description="API pedagógica · UFLA · v1.4.0",
    version="1.4.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────
# ESTADO EM MEMÓRIA (timer + carta-desafio por sessão)
# ─────────────────────────────────────────────────────────
# Estrutura: _timer_estado[sessao_id] = {total, restante, rodando, iniciado_em, mostrar_estudante}
# Estrutura: _carta_estado[sessao_id] = {chave, icone, titulo, corpo} | None
from datetime import timezone
import time as _time

_timer_estado: dict = {}
_carta_estado: dict = {}


def _timer_get(sessao_id: str) -> dict:
    t = _timer_estado.get(sessao_id, {})
    if not t:
        return {"total": 0, "restante": 0, "rodando": False, "mostrar_estudante": True}
    restante = t.get("restante", 0)
    if t.get("rodando") and t.get("iniciado_em"):
        elapsed = _time.time() - t["iniciado_em"]
        restante = max(0, t.get("restante_ao_iniciar", t["total"]) - elapsed)
        if restante == 0:
            t["rodando"] = False
            t["restante"] = 0
        else:
            t["restante_calculado"] = restante
    return {
        "total": t.get("total", 0),
        "restante": int(restante),
        "rodando": t.get("rodando", False),
        "mostrar_estudante": t.get("mostrar_estudante", True),
    }


def _timer_set(sessao_id: str, update: dict):
    t = _timer_estado.setdefault(sessao_id, {
        "total": 0, "restante": 0, "rodando": False,
        "mostrar_estudante": True, "iniciado_em": None,
    })
    if "total" in update:
        t["total"] = update["total"]
        t["restante"] = update["total"]
        t["rodando"] = False
        t["iniciado_em"] = None
    if "mostrar_estudante" in update:
        t["mostrar_estudante"] = update["mostrar_estudante"]
    acao = update.get("acao")
    if acao == "definir" and "total_seg" in update:
        t["total"] = update["total_seg"]
        t["restante"] = update["total_seg"]
        t["rodando"] = False
        t["iniciado_em"] = None
    elif acao == "iniciar":
        if not t.get("rodando") and t.get("total", 0) > 0:
            restante_atual = t.get("restante", t["total"])
            t["restante_ao_iniciar"] = restante_atual
            t["iniciado_em"] = _time.time()
            t["rodando"] = True
    elif acao == "parar":
        if t.get("rodando"):
            elapsed = _time.time() - (t.get("iniciado_em") or _time.time())
            t["restante"] = max(0, t.get("restante_ao_iniciar", t["total"]) - elapsed)
            t["rodando"] = False
            t["iniciado_em"] = None


class TimerAcao(BaseModel):
    acao: Optional[str] = None
    total: Optional[int] = None
    mostrar_estudante: Optional[bool] = None


class CartaDesafio(BaseModel):
    chave: str
    icone: str
    titulo: str
    corpo: str



# ─────────────────────────────────────────────────────────
# ROTAS — AUTH
# ─────────────────────────────────────────────────────────
@app.post("/auth/cadastro", tags=["Auth"])
def cadastrar(dados: UsuarioCriar):
    existente = db_find_one("usuarios", {"email": dados.email.lower()})
    if existente:
        raise HTTPException(409, "E-mail já cadastrado.")
    usuario = {
        "id": uid(), "nome": dados.nome, "sobrenome": dados.sobrenome,
        "email": dados.email.lower(), "instituicao": dados.instituicao,
        "perfil": "educador", "senha_hash": hash_senha(dados.senha),
        "criado_em": agora(),
    }
    db_insert("usuarios", usuario)
    token = criar_token({"sub": usuario["id"], "perfil": "educador"})
    return {
        "access_token": token,
        "usuario": {k: v for k, v in usuario.items() if k != "senha_hash"},
    }


@app.post("/auth/login", tags=["Auth"])
def login(dados: LoginEntrada):
    usuario = db_find_one("usuarios", {"email": dados.email.lower()})
    if not usuario or not verificar_senha(dados.senha, usuario["senha_hash"]):
        raise HTTPException(401, "E-mail ou senha incorretos.")
    token = criar_token({"sub": usuario["id"], "perfil": usuario["perfil"]})
    return {
        "access_token": token,
        "usuario": {k: v for k, v in usuario.items() if k != "senha_hash"},
    }


@app.get("/auth/me", tags=["Auth"])
def meu_perfil(edu=Depends(get_educador)):
    return {k: v for k, v in edu.items() if k != "senha_hash"}


# ─────────────────────────────────────────────────────────
# ROTAS — SESSÃO
# ─────────────────────────────────────────────────────────
@app.post("/sessao", tags=["Sessão"])
def criar_sessao(dados: SessaoCriar, edu=Depends(get_educador)):
    if not (1 <= dados.num_equipes <= 10):
        raise HTTPException(400, "Número de equipes deve ser entre 1 e 10.")
    while True:
        codigo = gerar_codigo()
        existente = supabase.table("sessoes").select("id").eq("codigo_acesso", codigo).execute()
        if not existente.data:
            break
    sid = uid()
    sessao = {
        "id": sid, "educador_id": edu["id"],
        "titulo": dados.titulo, "contexto": dados.contexto,
        "cenario": dados.cenario, "codigo_acesso": codigo,
        "status": "aguardando", "criada_em": agora(), "iniciada_em": None,
    }
    db_insert("sessoes", sessao)
    equipes = []
    for n in range(1, dados.num_equipes + 1):
        eid = uid()
        db_insert("equipes", {"id": eid, "sessao_id": sid,
                               "nome": f"Equipe {n}", "numero": n})
        _inicializar_progressos(eid)
        equipes.append({"id": eid, "nome": f"Equipe {n}"})
    return {**sessao, "equipes": equipes}


@app.get("/sessao", tags=["Sessão"])
def listar_sessoes(edu=Depends(get_educador)):
    sessoes = db_list("sessoes", {"educador_id": edu["id"]})
    return sorted(sessoes, key=lambda s: s["criada_em"], reverse=True)


@app.get("/sessao/{sessao_id}", tags=["Sessão"])
def detalhar_sessao(sessao_id: str, payload=Depends(get_usuario_atual)):
    sessao = db_get("sessoes", sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    perfil = payload.get("perfil")
    # Jogadores só vêem dados básicos da sua própria sessão
    if perfil not in ("educador", "instituicao"):
        tok_sessao = payload.get("sessao_id")
        if tok_sessao != sessao_id:
            raise HTTPException(403, "Acesso não autorizado para esta sessão.")
        return {
            "id": sessao["id"],
            "titulo": sessao["titulo"],
            "status": sessao["status"],
            "contexto": sessao["contexto"],
            "codigo_acesso": sessao["codigo_acesso"],
        }
    # Educadores vêem tudo
    equipes = sorted(
        db_list("equipes", {"sessao_id": sessao_id}),
        key=lambda e: e["numero"],
    )
    resultado = []
    for eq in equipes:
        chaves = resumo_chaves(eq["id"])
        concluidas = sum(1 for v in chaves.values() if v["status"] == "concluida")
        resultado.append({**eq, "chaves": chaves, "chaves_concluidas": concluidas})
    alertas_res = supabase.table("alertas").select("*").eq("sessao_id", sessao_id).eq("resolvido", False).execute()
    alertas = alertas_res.data or []
    return {**sessao, "equipes": resultado, "alertas": alertas}



# ─────────────────────────────────────────────────────────
# ROTAS — TIMER
# ─────────────────────────────────────────────────────────
@app.get("/sessao/{sessao_id}/timer", tags=["Timer"])
def ver_timer(sessao_id: str, payload=Depends(get_usuario_atual)):
    if not db_get("sessoes", sessao_id):
        raise HTTPException(404, "Sessão não encontrada.")
    return {"timer": _timer_get(sessao_id)}


@app.patch("/sessao/{sessao_id}/timer", tags=["Timer"])
def atualizar_timer(sessao_id: str, dados: TimerAcao, payload=Depends(get_usuario_atual)):
    if not db_get("sessoes", sessao_id):
        raise HTTPException(404, "Sessão não encontrada.")
    update: dict = {}
    if dados.acao:
        update["acao"] = dados.acao
    if dados.total is not None:
        update["total"] = dados.total
    if dados.mostrar_estudante is not None:
        update["mostrar_estudante"] = dados.mostrar_estudante
    _timer_set(sessao_id, update)
    return {"timer": _timer_get(sessao_id)}


# ─────────────────────────────────────────────────────────
# ROTAS — CARTA-DESAFIO
# ─────────────────────────────────────────────────────────
@app.get("/sessao/{sessao_id}/carta", tags=["Carta"])
def ver_carta(sessao_id: str, payload=Depends(get_usuario_atual)):
    if not db_get("sessoes", sessao_id):
        raise HTTPException(404, "Sessão não encontrada.")
    carta = _carta_estado.get(sessao_id)
    return {"carta": carta}


@app.post("/sessao/{sessao_id}/carta", tags=["Carta"])
def lancar_carta(sessao_id: str, dados: CartaDesafio, payload=Depends(get_usuario_atual)):
    if not db_get("sessoes", sessao_id):
        raise HTTPException(404, "Sessão não encontrada.")
    _carta_estado[sessao_id] = {
        "chave": dados.chave,
        "icone": dados.icone,
        "titulo": dados.titulo,
        "corpo": dados.corpo,
    }
    return {"ok": True, "carta": _carta_estado[sessao_id]}


@app.delete("/sessao/{sessao_id}/carta", tags=["Carta"])
def remover_carta(sessao_id: str, payload=Depends(get_usuario_atual)):
    _carta_estado.pop(sessao_id, None)
    return {"ok": True}


@app.delete("/sessao/{sessao_id}", tags=["Sessão"])
def excluir_sessao(sessao_id: str, edu=Depends(get_educador)):
    sessao = db_get("sessoes", sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    if sessao["educador_id"] != edu["id"]:
        raise HTTPException(403, "Você não tem permissão para excluir esta sessão.")
    equipes = db_list("equipes", {"sessao_id": sessao_id})
    for eq in equipes:
        progs = db_list("progresso_chaves", {"equipe_id": eq["id"]})
        for prog in progs:
            supabase.table("progresso_fases").delete().eq("progresso_chave_id", prog["id"]).execute()
        supabase.table("progresso_chaves").delete().eq("equipe_id", eq["id"]).execute()
        supabase.table("participantes").delete().eq("equipe_id", eq["id"]).execute()
        supabase.table("cutucar").delete().eq("equipe_id", eq["id"]).execute()
        supabase.table("sussurros").delete().eq("equipe_id", eq["id"]).execute()
        supabase.table("baloes_coletivos").delete().eq("equipe_id", eq["id"]).execute()
    supabase.table("equipes").delete().eq("sessao_id", sessao_id).execute()
    supabase.table("alertas").delete().eq("sessao_id", sessao_id).execute()
    supabase.table("sessoes").delete().eq("id", sessao_id).execute()
    return {"ok": True, "excluida": sessao_id}


@app.patch("/sessao/{sessao_id}/acao", tags=["Sessão"])
def acao_sessao(sessao_id: str, dados: SessaoAcao, edu=Depends(get_educador)):
    sessao = db_get("sessoes", sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    transicoes = {
        "iniciar":    ("aguardando", "ativa"),
        "pausar":     ("ativa",      "pausada"),
        "retomar":    ("pausada",    "ativa"),
        "socializar": ("ativa",      "socializando"),
        "encerrar":   (None,         "encerrada"),
    }
    if dados.acao not in transicoes:
        raise HTTPException(400, f"Ação inválida: {dados.acao}.")
    origem, destino = transicoes[dados.acao]
    if origem and sessao["status"] != origem:
        raise HTTPException(400, f"Sessão precisa estar '{origem}' para '{dados.acao}'.")
    update_data = {"status": destino}
    if dados.acao == "iniciar":
        update_data["iniciada_em"] = agora()
    sessao = db_update("sessoes", sessao_id, update_data)
    return sessao


# ─────────────────────────────────────────────────────────
# ROTAS — JOGADOR
# ─────────────────────────────────────────────────────────
@app.post("/entrar", tags=["Jogador"])
def entrar_com_codigo(dados: EntrarComCodigo):
    res = supabase.table("sessoes").select("*").eq("codigo_acesso", dados.codigo.upper()).execute()
    sessao = res.data[0] if res.data else None
    if not sessao:
        raise HTTPException(404, "Código de sessão inválido.")
    if sessao["status"] not in ("aguardando", "ativa"):
        raise HTTPException(400, "Sessão não está aceitando participantes.")
    res2 = supabase.table("equipes").select("*").eq("sessao_id", sessao["id"]).eq("numero", dados.numero_equipe).execute()
    equipe = res2.data[0] if res2.data else None
    if not equipe:
        raise HTTPException(404, f"Equipe {dados.numero_equipe} não encontrada.")
    pid = uid()
    db_insert("participantes", {
        "id": pid, "equipe_id": equipe["id"],
        "nome": dados.nome, "entrou_em": agora(),
    })
    token = criar_token({
        "sub": pid, "perfil": "jogador",
        "equipe_id": equipe["id"], "sessao_id": sessao["id"],
    })
    return {
        "access_token": token,
        "sessao_titulo": sessao["titulo"],
        "sessao_id": sessao["id"],
        "equipe_id": equipe["id"],
        "equipe_nome": equipe["nome"],
    }


# ─────────────────────────────────────────────────────────
# ROTAS — CHAVES
# ─────────────────────────────────────────────────────────
@app.get("/chaves/{equipe_id}", tags=["Chaves"])
def ver_chaves(equipe_id: str, payload=Depends(get_usuario_atual)):
    if not db_get("equipes", equipe_id):
        raise HTTPException(404, "Equipe não encontrada.")
    return resumo_chaves(equipe_id)


@app.post("/chaves/{equipe_id}/ativar", tags=["Chaves"])
def ativar_chave(equipe_id: str, dados: AtivarChave,
                 payload=Depends(get_usuario_atual)):
    chave = dados.chave.lower()
    if chave not in FASES_POR_CHAVE:
        raise HTTPException(400, f"Chave '{chave}' inválida.")
    if chave in CHAVES_LIVRES:
        prob = _progresso(equipe_id, "problema")
        if not prob or prob["status"] != "concluida":
            raise HTTPException(
                400, f"Conclua Problema antes de ativar {chave.title()}."
            )
    prog = _progresso(equipe_id, chave)
    if not prog:
        raise HTTPException(404, "Progresso não encontrado.")
    if prog["status"] == "concluida":
        raise HTTPException(400, f"{chave.title()} já está concluída.")
    db_update("progresso_chaves", prog["id"], {
        "status": "ativa",
        "iniciada_em": prog["iniciada_em"] or agora(),
        "ultima_atividade_em": agora(),
    })
    fases = _fases(prog["id"])
    if fases and fases[0]["status"] == "bloqueada":
        db_update("progresso_fases", fases[0]["id"], {"status": "disponivel"})
    return resumo_chaves(equipe_id)[chave]


@app.post("/chaves/{equipe_id}/concluir-fase", tags=["Chaves"])
def concluir_fase(equipe_id: str, dados: ConcluirFase,
                  payload=Depends(get_usuario_atual)):
    chave = dados.chave.lower()
    prog = _progresso(equipe_id, chave)
    if not prog:
        raise HTTPException(404, "Chave não encontrada.")
    fases = _fases(prog["id"])
    fase = next((f for f in fases if f["numero_fase"] == dados.numero_fase), None)
    if not fase:
        raise HTTPException(404, f"Fase {dados.numero_fase} não encontrada.")
    if fase["status"] == "bloqueada":
        raise HTTPException(400, "Esta fase ainda está bloqueada.")
    db_update("progresso_fases", fase["id"], {
        "status": "concluida",
        "conteudo": dados.conteudo,
        "concluida_em": agora(),
    })
    db_update("progresso_chaves", prog["id"], {"ultima_atividade_em": agora()})
    proxima = next(
        (f for f in fases if f["numero_fase"] == dados.numero_fase + 1), None
    )
    if proxima:
        db_update("progresso_fases", proxima["id"], {"status": "disponivel"})
    else:
        db_update("progresso_chaves", prog["id"], {
            "status": "concluida",
            "concluida_em": agora(),
        })
        if chave == "problema":
            _liberar_chaves_livres(equipe_id)
    return {
        "fase_concluida": {"numero": fase["numero_fase"], "nome": fase["nome_fase"]},
        "chave_status": "concluida" if not proxima else prog["status"],
        "chaves_atualizadas": resumo_chaves(equipe_id),
    }


# ─────────────────────────────────────────────────────────
# ROTAS — ALERTAS
# ─────────────────────────────────────────────────────────
@app.post("/alertas/{sessao_id}/verificar", tags=["Alertas"])
def verificar_alertas(sessao_id: str, edu=Depends(get_educador)):
    sessao = db_get("sessoes", sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    equipes = db_list("equipes", {"sessao_id": sessao_id})
    novos = []
    contagens = {}
    for eq in equipes:
        progs = db_list("progresso_chaves", {"equipe_id": eq["id"]})
        contagens[eq["id"]] = sum(1 for p in progs if p["status"] == "concluida")
    if contagens:
        max_c = max(contagens.values())
        media = sum(contagens.values()) / len(contagens)
        if max_c >= 2 and max_c > media + 1:
            lider_id = max(contagens, key=lambda k: contagens[k])
            ja_existe = supabase.table("alertas").select("id").eq("sessao_id", sessao_id).eq("equipe_id", lider_id).eq("tipo", "equipe_avancada").eq("resolvido", False).execute()
            if not ja_existe.data:
                lider = db_get("equipes", lider_id)
                aid = uid()
                alerta = {
                    "id": aid, "sessao_id": sessao_id, "equipe_id": lider_id,
                    "tipo": "equipe_avancada",
                    "mensagem": f"{lider['nome']} está mais avançada ({max_c} chaves).",
                    "sugestao": f"Peça à {lider['nome']} que compartilhe o raciocínio.",
                    "resolvido": False, "criado_em": agora(),
                }
                db_insert("alertas", alerta)
                novos.append(alerta)
    return {"novos_alertas": novos, "total": len(novos)}


@app.patch("/alertas/{alerta_id}/resolver", tags=["Alertas"])
def resolver_alerta(alerta_id: str, edu=Depends(get_educador)):
    alerta = db_get("alertas", alerta_id)
    if not alerta:
        raise HTTPException(404, "Alerta não encontrado.")
    return db_update("alertas", alerta_id, {"resolvido": True, "resolvido_em": agora()})


# ─────────────────────────────────────────────────────────
# ROTAS — SOCIALIZAÇÃO / PITCH
# ─────────────────────────────────────────────────────────
@app.get("/pitch/{sessao_id}", tags=["Socialização"])
def pitch_sessao(sessao_id: str, payload=Depends(get_usuario_atual)):
    sessao = db_get("sessoes", sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    equipes = sorted(
        db_list("equipes", {"sessao_id": sessao_id}),
        key=lambda e: e["numero"],
    )
    cards = []
    for eq in equipes:
        chaves = resumo_chaves(eq["id"])
        concluidas = sum(1 for v in chaves.values() if v["status"] == "concluida")
        proposta = None
        for chave in chaves:
            prog = _progresso(eq["id"], chave)
            if prog:
                for fase in reversed(_fases(prog["id"])):
                    if fase["status"] == "concluida" and fase["conteudo"]:
                        proposta = fase["conteudo"]
                        break
            if proposta:
                break
        cards.append({
            "equipe_id": eq["id"], "equipe_nome": eq["nome"],
            "chaves_concluidas": concluidas,
            "chaves": {k: v["status"] for k, v in chaves.items()},
            "proposta": proposta or "Em construção...",
        })
    cards.sort(key=lambda c: c["chaves_concluidas"], reverse=True)
    return {
        "sessao_id": sessao_id, "titulo": sessao["titulo"],
        "contexto": sessao["contexto"], "equipes": cards,
    }


# ─────────────────────────────────────────────────────────
# ROTAS — COMUNICAÇÃO DA EQUIPE
# ─────────────────────────────────────────────────────────
def _nome_participante(pid: str) -> str:
    p = db_get("participantes", pid)
    return p["nome"] if p else "Desconhecido"

def _validar_equipe_participante(equipe_id: str, participante_id: str):
    if not db_get("equipes", equipe_id):
        raise HTTPException(404, "Equipe não encontrada.")
    p = db_get("participantes", participante_id)
    if not p:
        raise HTTPException(404, "Participante não encontrado.")
    if p["equipe_id"] != equipe_id:
        raise HTTPException(403, "Participante não pertence a esta equipe.")


@app.post("/comunicacao/cutucar", tags=["Comunicacao"])
def cutucar(dados: CutucarEntrada, payload=Depends(get_usuario_atual)):
    _validar_equipe_participante(dados.equipe_id, dados.de_participante_id)
    _validar_equipe_participante(dados.equipe_id, dados.para_participante_id)
    if dados.de_participante_id == dados.para_participante_id:
        raise HTTPException(400, "Não é possível cutucar a si mesmo.")
    cid = uid()
    registro = {
        "id": cid, "tipo": "cutucar", "equipe_id": dados.equipe_id,
        "de_id": dados.de_participante_id,
        "de_nome": _nome_participante(dados.de_participante_id),
        "para_id": dados.para_participante_id,
        "para_nome": _nome_participante(dados.para_participante_id),
        "lido": False, "criado_em": agora(),
    }
    db_insert("cutucar", registro)
    return {"ok": True, "mensagem": f"{registro['de_nome']} cutucou {registro['para_nome']}."}


@app.get("/comunicacao/cutucar/{equipe_id}/{participante_id}", tags=["Comunicacao"])
def ver_cutucar(equipe_id: str, participante_id: str,
                payload=Depends(get_usuario_atual)):
    res = supabase.table("cutucar").select("*").eq("equipe_id", equipe_id).eq("para_id", participante_id).eq("lido", False).execute()
    pendentes = res.data or []
    return {"pendentes": len(pendentes), "cutucares": pendentes}


@app.patch("/comunicacao/cutucar/{cutucar_id}/lido", tags=["Comunicacao"])
def marcar_cutucar_lido(cutucar_id: str, payload=Depends(get_usuario_atual)):
    c = db_get("cutucar", cutucar_id)
    if not c:
        raise HTTPException(404, "Cutucar não encontrado.")
    db_update("cutucar", cutucar_id, {"lido": True})
    return {"ok": True}


@app.post("/comunicacao/sussurro", tags=["Comunicacao"])
def enviar_sussurro(dados: SussurroEntrada, payload=Depends(get_usuario_atual)):
    _validar_equipe_participante(dados.equipe_id, dados.de_participante_id)
    _validar_equipe_participante(dados.equipe_id, dados.para_participante_id)
    if dados.de_participante_id == dados.para_participante_id:
        raise HTTPException(400, "Não é possível enviar sussurro para si mesmo.")
    if not dados.mensagem.strip():
        raise HTTPException(400, "Mensagem vazia.")
    sid = uid()
    db_insert("sussurros", {
        "id": sid, "tipo": "sussurro", "equipe_id": dados.equipe_id,
        "de_id": dados.de_participante_id,
        "de_nome": _nome_participante(dados.de_participante_id),
        "para_id": dados.para_participante_id,
        "para_nome": _nome_participante(dados.para_participante_id),
        "mensagem": dados.mensagem.strip(),
        "lido": False, "criado_em": agora(),
    })
    return {"ok": True, "id": sid}


@app.get("/comunicacao/sussurro/{equipe_id}/{participante_id}", tags=["Comunicacao"])
def ver_sussurros(equipe_id: str, participante_id: str,
                  payload=Depends(get_usuario_atual)):
    res = supabase.table("sussurros").select("*").eq("equipe_id", equipe_id).eq("para_id", participante_id).execute()
    recebidos = sorted(res.data or [], key=lambda s: s["criado_em"])
    return {"total": len(recebidos), "sussurros": recebidos}


@app.post("/comunicacao/balao", tags=["Comunicacao"])
def enviar_balao(dados: BalaoColetivo, payload=Depends(get_usuario_atual)):
    _validar_equipe_participante(dados.equipe_id, dados.participante_id)
    if not dados.mensagem.strip():
        raise HTTPException(400, "Mensagem vazia.")
    bid = uid()
    registro = {
        "id": bid, "tipo": "balao_coletivo", "equipe_id": dados.equipe_id,
        "de_id": dados.participante_id,
        "de_nome": _nome_participante(dados.participante_id),
        "mensagem": dados.mensagem.strip(), "criado_em": agora(),
    }
    db_insert("baloes_coletivos", registro)
    return {"ok": True, "registro": registro}


@app.get("/comunicacao/balao/{equipe_id}", tags=["Comunicacao"])
def ver_baloes(equipe_id: str, payload=Depends(get_usuario_atual)):
    res = supabase.table("baloes_coletivos").select("*").eq("equipe_id", equipe_id).execute()
    baloes = sorted(res.data or [], key=lambda b: b["criado_em"])
    return {"total": len(baloes), "baloes": baloes}


@app.get("/comunicacao/registro/{equipe_id}", tags=["Comunicacao"])
def chat_registro(equipe_id: str, payload=Depends(get_usuario_atual)):
    sub = payload.get("sub", "")
    eventos = []
    cutucares = supabase.table("cutucar").select("*").eq("equipe_id", equipe_id).execute().data or []
    for c in cutucares:
        eventos.append({
            "tipo": "cutucar",
            "descricao": f"{c['de_nome']} cutucou {c['para_nome']}",
            "conteudo": None, "criado_em": c["criado_em"],
        })
    sussurros = supabase.table("sussurros").select("*").eq("equipe_id", equipe_id).execute().data or []
    for s in sussurros:
        e_participante = sub in (s["de_id"], s["para_id"])
        eventos.append({
            "tipo": "sussurro",
            "descricao": f"{s['de_nome']} → {s['para_nome']} (sussurro)",
            "conteudo": s["mensagem"] if e_participante else None,
            "criado_em": s["criado_em"],
        })
    baloes = supabase.table("baloes_coletivos").select("*").eq("equipe_id", equipe_id).execute().data or []
    for b in baloes:
        eventos.append({
            "tipo": "balao_coletivo",
            "descricao": b["mensagem"],
            "conteudo": b["mensagem"], "criado_em": b["criado_em"],
        })
    eventos.sort(key=lambda e: e["criado_em"])
    return {"total": len(eventos), "eventos": eventos}


# ─────────────────────────────────────────────────────────
# ROTAS — NOVAS FUNÇÕES
# ─────────────────────────────────────────────────────────
@app.get("/novas-funcoes", tags=["Novas Funcoes"])
def listar_novas_funcoes():
    return {
        "status": "em_breve",
        "funcionalidades": [
            {"id": "desafios_extras",    "nome": "Desafios extras",      "icone": "⚡",
             "descricao": "Baralho adicional lançado manualmente pelo educador.",
             "status": "em_breve"},
            {"id": "coringas",           "nome": "Coringas",             "icone": "🃏",
             "descricao": "Cartas especiais usadas uma vez por sessão pela equipe.",
             "status": "em_breve"},
            {"id": "cartas_pedagogicas", "nome": "Cartas pedagógicas",   "icone": "📚",
             "descricao": "Cartões com conceitos e perguntas geradoras para apoio.",
             "status": "em_breve"},
        ],
    }


# ─────────────────────────────────────────────────────────
# ROTAS — RPG
# ─────────────────────────────────────────────────────────
PAPEIS_RPG = [
    {"id": "agente_saude",       "nome": "Agente de Saúde",      "icone": "🩺",
     "titulo": "Investigador do bem-estar",
     "descricao": "Observa impactos do problema na saúde e qualidade de vida.",
     "perspectiva": "Quem está sofrendo? Como isso afeta o corpo e a rotina?",
     "missao_detalhe": "Investigue os sintomas sociais — quem sofre mais e por quê.",
     "cor": "#22C97A"},
    {"id": "lider_comunitario",  "nome": "Líder Comunitário",    "icone": "🏘️",
     "titulo": "Voz do território",
     "descricao": "Representa as pessoas do bairro e conhece as dinâmicas locais.",
     "perspectiva": "O que a comunidade já tentou? Quem tem poder aqui?",
     "missao_detalhe": "Mapeie as forças — quem apoia, quem resiste e quais recursos existem.",
     "cor": "#0FD4B0"},
    {"id": "jovem_empreendedor", "nome": "Jovem Empreendedor",   "icone": "🚀",
     "titulo": "Criador de soluções",
     "descricao": "Pensa em como transformar o problema em oportunidade sustentável.",
     "perspectiva": "O que ainda não existe aqui? Que solução poderia ser replicada?",
     "missao_detalhe": "Identifique onde a solução pode criar mais valor para o lugar.",
     "cor": "#2E80F0"},
    {"id": "pesquisador",        "nome": "Pesquisador",           "icone": "🔬",
     "titulo": "Investigador de dados",
     "descricao": "Busca evidências e contextos que explicam por que o problema existe.",
     "perspectiva": "Quais são os dados? O que já foi estudado? Qual a raiz?",
     "missao_detalhe": "Levante evidências — o que os dados dizem sobre o problema.",
     "cor": "#A040E0"},
]

CENARIOS_RPG = {
    "escolar": {
        "titulo": "Bairro Novo Horizonte",
        "texto_abertura": "É segunda-feira de manhã no Bairro Novo Horizonte. A escola está cheia, mas algo está errado — as crianças chegam sem energia, a merenda é sempre a mesma coisa, e as famílias estão preocupadas. Vocês são uma equipe de investigação convocada para descobrir o problema e propor uma solução que o bairro possa realizar.",
        "missao": "Mapeie o território — descubra quem sofre com o problema e por quê",
        "npcs": [
            {"nome": "Diretora Ana",  "papel": "Gestora da escola",        "icone": "👩‍💼"},
            {"nome": "Sr. Carlos",    "papel": "Líder do bairro",          "icone": "🧑‍🤝‍🧑"},
            {"nome": "Dra. Marina",   "papel": "Nutricionista local",      "icone": "👩‍⚕️"},
            {"nome": "João (aluno)",  "papel": "Representante estudantil", "icone": "🎒"},
        ],
    },
    "gestao": {
        "titulo": "Cooperativa Vale Verde",
        "texto_abertura": "A Cooperativa Vale Verde está em crise. Os produtores locais não conseguem escoar sua produção e a concorrência está sufocando o negócio. Vocês são uma equipe de investigação contratada para mapear o problema e construir uma proposta de transformação.",
        "missao": "Mapeie o território — entenda o contexto da crise",
        "npcs": [
            {"nome": "Presidente Maria", "papel": "Líder da cooperativa",   "icone": "👩‍💼"},
            {"nome": "Produtor Paulo",   "papel": "Agricultor familiar",    "icone": "🧑‍🌾"},
            {"nome": "Técnica Lúcia",    "papel": "Especialista em vendas", "icone": "👩‍💻"},
            {"nome": "Vereador Hélio",   "papel": "Poder público local",    "icone": "🏛️"},
        ],
    },
    "superior": {
        "titulo": "Campus UFLA — Laboratório de Inovação",
        "texto_abertura": "O Laboratório de Inovação Social da UFLA recebeu uma demanda real da comunidade. Vocês são pesquisadores-empreendedores convocados para investigar, validar hipóteses e construir uma proposta aplicável.",
        "missao": "Defina o problema de pesquisa — contexto e evidências",
        "npcs": [
            {"nome": "Prof. Daniela",      "papel": "Orientadora da pesquisa", "icone": "👩‍🏫"},
            {"nome": "Diego (mestrando)",  "papel": "Pesquisador de campo",    "icone": "🎓"},
            {"nome": "Secretária Cláudia", "papel": "Prefeitura de Lavras",    "icone": "🏛️"},
            {"nome": "Comunidade",         "papel": "Usuários do serviço",     "icone": "👥"},
        ],
    },
}


@app.get("/rpg/papeis", tags=["RPG"])
def listar_papeis():
    return {"papeis": PAPEIS_RPG}


@app.get("/rpg/cenario/{contexto}", tags=["RPG"])
def buscar_cenario(contexto: str):
    cen = CENARIOS_RPG.get(contexto)
    if not cen:
        raise HTTPException(404, f"Cenário '{contexto}' não encontrado.")
    return {"contexto": contexto, **cen}


@app.post("/rpg/papel", tags=["RPG"])
def registrar_papel(dados: PapelRPGEntrada, payload=Depends(get_usuario_atual)):
    papel_valido = next((p for p in PAPEIS_RPG if p["id"] == dados.papel_id), None)
    if not papel_valido:
        raise HTTPException(400, f"Papel '{dados.papel_id}' inválido.")
    rid = uid()
    db_insert("papeis_rpg", {
        "id": rid, "participante_id": dados.participante_id,
        "papel_id": dados.papel_id, "papel_nome": dados.papel_nome,
        "papel_icone": dados.papel_icone, "papel_cor": dados.papel_cor,
        "registrado_em": agora(),
    })
    return {"ok": True, "papel": papel_valido}


@app.get("/rpg/papel/{participante_id}", tags=["RPG"])
def buscar_papel_participante(participante_id: str,
                              payload=Depends(get_usuario_atual)):
    res = supabase.table("papeis_rpg").select("*").eq("participante_id", participante_id).execute()
    if not res.data:
        raise HTTPException(404, "Participante ainda não escolheu um papel.")
    return res.data[0]


@app.get("/rpg/equipe/{equipe_id}", tags=["RPG"])
def papeis_da_equipe(equipe_id: str, payload=Depends(get_usuario_atual)):
    participantes = db_list("participantes", {"equipe_id": equipe_id})
    resultado = []
    for part in participantes:
        res = supabase.table("papeis_rpg").select("*").eq("participante_id", part["id"]).execute()
        papel = res.data[0] if res.data else None
        resultado.append({"participante_id": part["id"],
                          "nome": part["nome"], "papel": papel})
    return {"equipe_id": equipe_id, "membros": resultado}


@app.get("/rpg/missoes/{chave}", tags=["RPG"])
def missoes_por_chave(chave: str):
    missoes = {
        "problema": {
            "nome_rpg": "Investigação do Território",
            "fases": [
                {"numero": 1, "nome": "Contexto",
                 "missao": "Mapeie o território — onde o problema acontece e em que condições.",
                 "objetivo": "Descreva o espaço, o tempo e as circunstâncias em que o problema se manifesta."},
                {"numero": 2, "nome": "Características",
                 "missao": "Identifique os afetados — quem sofre, quanto e de que forma.",
                 "objetivo": "Descreva as pessoas afetadas, a intensidade e suas variações."},
                {"numero": 3, "nome": "Motivação",
                 "missao": "Descubra a raiz — por que o problema persiste e quem tem interesse nisso.",
                 "objetivo": "Explique por que o problema não foi resolvido e quais forças o mantêm."},
            ],
        },
        "solucao": {
            "nome_rpg": "Construção da Resposta",
            "fases": [
                {"numero": 1, "nome": "Características",
                 "missao": "Desenhe a solução — como ela funciona na prática.",
                 "objetivo": "Descreva a solução, seus componentes e como endereça o problema."},
                {"numero": 2, "nome": "Custos",
                 "missao": "Calcule o preço — o que será necessário para realizar.",
                 "objetivo": "Liste os recursos necessários para implementar a solução."},
                {"numero": 3, "nome": "Riscos",
                 "missao": "Identifique as ameaças — o que pode dar errado e como prevenir.",
                 "objetivo": "Descreva os riscos e como a equipe planeja mitigá-los."},
            ],
        },
        "parcerias": {
            "nome_rpg": "Mapa de Aliados",
            "fases": [
                {"numero": 1, "nome": "Recursos",
                 "missao": "Mapeie os recursos — o que já existe e pode ser usado.",
                 "objetivo": "Identifique recursos disponíveis: pessoas, espaços, materiais."},
                {"numero": 2, "nome": "Características",
                 "missao": "Encontre os aliados — quem pode embarcar nesta causa.",
                 "objetivo": "Descreva os parceiros potenciais e como cada um contribui."},
                {"numero": 3, "nome": "Tempo",
                 "missao": "Defina o cronograma — quando cada parceiro entra em ação.",
                 "objetivo": "Esboce um plano temporal para envolver os parceiros."},
            ],
        },
        "oportunidades": {
            "nome_rpg": "Horizonte de Impacto",
            "fases": [
                {"numero": 1, "nome": "Características",
                 "missao": "Veja o potencial — o que esta solução pode gerar além do problema.",
                 "objetivo": "Descreva as oportunidades secundárias que a solução pode criar."},
                {"numero": 2, "nome": "Diferenciação",
                 "missao": "Destaque o diferencial — o que torna esta proposta única.",
                 "objetivo": "Explique por que esta solução é diferente do que já existe."},
                {"numero": 3, "nome": "Aplicabilidade",
                 "missao": "Prove que funciona — onde e como pode ser replicada.",
                 "objetivo": "Descreva onde mais a solução poderia ser aplicada."},
            ],
        },
    }
    if chave not in missoes:
        raise HTTPException(404, f"Chave '{chave}' não encontrada.")
    return missoes[chave]


# ─────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────
@app.get("/health", tags=["Sistema"])
def health():
    try:
        usuarios = supabase.table("usuarios").select("id", count="exact").execute()
        sessoes = supabase.table("sessoes").select("id", count="exact").execute()
        equipes = supabase.table("equipes").select("id", count="exact").execute()
        cutucares = supabase.table("cutucar").select("id", count="exact").execute()
        sussurros = supabase.table("sussurros").select("id", count="exact").execute()
        baloes = supabase.table("baloes_coletivos").select("id", count="exact").execute()
        papeis = supabase.table("papeis_rpg").select("id", count="exact").execute()
        return {
            "status": "ok", "app": "TdoE", "versao": "1.3.0",
            "db": "supabase",
            "usuarios": usuarios.count or 0,
            "sessoes": sessoes.count or 0,
            "equipes": equipes.count or 0,
            "comunicacao": {
                "cutucares": cutucares.count or 0,
                "sussurros": sussurros.count or 0,
                "baloes": baloes.count or 0,
            },
            "rpg": {
                "papeis_disponiveis": len(PAPEIS_RPG),
                "cenarios_disponiveis": len(CENARIOS_RPG),
                "papeis_registrados": papeis.count or 0,
            },
        }
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def pagina_inicial():
    return """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"/>
<title>TdoE API v1.3.0</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:system-ui,sans-serif;background:#08080F;color:#e8e6e0;padding:40px 24px;}
h1{font-size:36px;font-weight:900;background:linear-gradient(125deg,#22C97A,#0FD4B0,#2E80F0,#A040E0);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:4px;}
.bar{height:2px;background:linear-gradient(90deg,#22C97A,#0FD4B0,#2E80F0,#A040E0);margin:16px 0 28px;border-radius:2px;}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;}
.card{background:#141422;border:.5px solid rgba(255,255,255,.1);border-radius:13px;padding:18px;}
.card h3{font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;margin-bottom:11px;}
.r{background:#0E0E1C;border:.5px solid rgba(255,255,255,.07);border-radius:8px;
  padding:8px 11px;margin-bottom:7px;font-size:11px;}
.m{display:inline-block;padding:2px 7px;border-radius:4px;font-size:9px;font-weight:700;margin-right:6px;}
.g{background:rgba(46,128,240,.2);color:#2E80F0;}
.p{background:rgba(34,201,122,.2);color:#22C97A;}
.pa{background:rgba(240,188,64,.2);color:#F0BC40;}
.d{font-size:9px;color:#444;margin-top:3px;}
.cta{margin-top:22px;display:flex;gap:10px;}
.btn{padding:10px 20px;border-radius:9px;font-size:13px;font-weight:700;text-decoration:none;}
.b1{background:linear-gradient(135deg,#2E80F0,#5B6CF0);color:#fff;}
.b2{background:rgba(255,255,255,.05);color:#888;border:.5px solid rgba(255,255,255,.12);}
.badge{display:inline-block;background:rgba(34,201,122,.15);color:#22C97A;border:1px solid rgba(34,201,122,.3);
  border-radius:6px;padding:2px 8px;font-size:10px;font-weight:700;margin-left:8px;}
</style></head><body>
<p style="color:#555;font-size:11px;margin-bottom:6px;">★ TdoE · UFLA</p>
<h1>Tabuleiro do Empreendedor <span class="badge">v1.3.0 · Supabase</span></h1>
<p style="color:#555;font-size:13px;">API pedagógica · persistência em nuvem</p>
<div class="bar"></div>
<div class="grid">
<div class="card"><h3 style="color:#22C97A">🔐 Auth</h3>
  <div class="r"><span class="m p">POST</span>/auth/cadastro<div class="d">Cadastrar educador</div></div>
  <div class="r"><span class="m p">POST</span>/auth/login<div class="d">Login com e-mail e senha</div></div>
  <div class="r"><span class="m g">GET</span>/auth/me<div class="d">Perfil autenticado</div></div>
</div>
<div class="card"><h3 style="color:#2E80F0">📋 Sessão</h3>
  <div class="r"><span class="m p">POST</span>/sessao<div class="d">Criar sessão + equipes</div></div>
  <div class="r"><span class="m g">GET</span>/sessao<div class="d">Listar sessões</div></div>
  <div class="r"><span class="m g">GET</span>/sessao/{id}<div class="d">Detalhes + progresso</div></div>
  <div class="r"><span class="m pa">PATCH</span>/sessao/{id}/acao<div class="d">iniciar · pausar · encerrar</div></div>
</div>
<div class="card"><h3 style="color:#0FD4B0">🎮 Jogo</h3>
  <div class="r"><span class="m p">POST</span>/entrar<div class="d">Jogador entra com código</div></div>
  <div class="r"><span class="m g">GET</span>/chaves/{equipe_id}<div class="d">Estado das 4 chaves</div></div>
  <div class="r"><span class="m p">POST</span>/chaves/{id}/ativar<div class="d">Ativar chave</div></div>
  <div class="r"><span class="m p">POST</span>/chaves/{id}/concluir-fase<div class="d">Concluir fase</div></div>
</div>
<div class="card"><h3 style="color:#A040E0">⚡ Alertas + Pitch</h3>
  <div class="r"><span class="m p">POST</span>/alertas/{id}/verificar<div class="d">Detectar equipes paradas</div></div>
  <div class="r"><span class="m pa">PATCH</span>/alertas/{id}/resolver<div class="d">Resolver alerta</div></div>
  <div class="r"><span class="m g">GET</span>/pitch/{sessao_id}<div class="d">Mural de socialização</div></div>
</div>
<div class="card"><h3 style="color:#0FD4B0">💬 Comunicação</h3>
  <div class="r"><span class="m p">POST</span>/comunicacao/cutucar<div class="d">① Cutucar membro</div></div>
  <div class="r"><span class="m p">POST</span>/comunicacao/sussurro<div class="d">② Mensagem privada</div></div>
  <div class="r"><span class="m p">POST</span>/comunicacao/balao<div class="d">③ Balão coletivo</div></div>
  <div class="r"><span class="m g">GET</span>/comunicacao/registro/{id}<div class="d">④ Chat de registro</div></div>
</div>
<div class="card"><h3 style="color:#F0BC40">🎲 RPG</h3>
  <div class="r"><span class="m g">GET</span>/rpg/papeis<div class="d">4 papéis narrativos</div></div>
  <div class="r"><span class="m g">GET</span>/rpg/cenario/{contexto}<div class="d">Cenário + NPCs</div></div>
  <div class="r"><span class="m p">POST</span>/rpg/papel<div class="d">Registrar papel do jogador</div></div>
  <div class="r"><span class="m g">GET</span>/rpg/missoes/{chave}<div class="d">Missões narrativas</div></div>
</div>
</div>
<div class="cta">
  <a href="/docs" class="btn b1">📖 Documentação interativa →</a>
  <a href="/health" class="btn b2">✓ Health check</a>
</div>
</body></html>"""


# ─────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    env_port = int(os.environ.get("PORT", 0))
    porta = env_port if env_port else porta_livre(8000)
    host  = "0.0.0.0" if env_port else "127.0.0.1"
    print()
    print("  ★  TdoE — Tabuleiro do Empreendedor  v1.3.0")
    print("  ─────────────────────────────────────────────")
    print(f"  Interface:     http://localhost:{porta}")
    print(f"  Documentação:  http://localhost:{porta}/docs")
    print(f"  Health:        http://localhost:{porta}/health")
    print(f"  Banco:         Supabase ({SUPABASE_URL})")
    print()
    uvicorn.run(app, host=host, port=porta, reload=False, log_level="warning")
