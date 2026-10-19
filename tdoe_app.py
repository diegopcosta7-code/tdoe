"""
TdoE — Tabuleiro do Empreendedor · API v1.2.0
==============================================
Back-end FastAPI · banco em memória · compatível com Spyder e terminal.

COMO RODAR
----------
Terminal / CMD:
    cd Downloads
    python tdoe_app.py

Spyder:
    Abra o arquivo e pressione F5.

Dependências (instalar uma vez):
    pip install fastapi uvicorn python-jose
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
from datetime import datetime, timedelta
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jose import jwt, JWTError


# ─────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────
SECRET_KEY  = "tdoe-chave-secreta-2025-ufla"
ALGORITHM   = "HS256"
TOKEN_HORAS = 8

FASES_POR_CHAVE = {
    "problema":      ["Contexto", "Características", "Motivação"],
    "solucao":       ["Características", "Custos", "Riscos"],
    "parcerias":     ["Recursos", "Características", "Tempo"],
    "oportunidades": ["Características", "Diferenciação", "Aplicabilidade"],
}
CHAVES_LIVRES = {"solucao", "parcerias", "oportunidades"}


# ─────────────────────────────────────────────────────────
# BANCO EM MEMÓRIA
# ─────────────────────────────────────────────────────────
DB = {
    "usuarios":         {},
    "sessoes":          {},
    "equipes":          {},
    "participantes":    {},
    "progresso_chaves": {},
    "progresso_fases":  {},
    "alertas":          {},
    # Comunicação
    "cutucar":          {},
    "sussurros":        {},
    "baloes_coletivos": {},
    # Novas funções (reservado)
    "novas_funcoes":    {},
    # RPG
    "papeis_rpg":       {},
    "cenarios_rpg":     {},
}


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
    usuario = DB["usuarios"].get(payload["sub"])
    if not usuario:
        raise HTTPException(401, "Usuário não encontrado.")
    return usuario


# ─────────────────────────────────────────────────────────
# LÓGICA PEDAGÓGICA
# ─────────────────────────────────────────────────────────
def _inicializar_progressos(equipe_id: str):
    for chave, fases_nomes in FASES_POR_CHAVE.items():
        pid = uid()
        DB["progresso_chaves"][pid] = {
            "id": pid, "equipe_id": equipe_id, "chave": chave,
            "status": "nao_iniciada",
            "iniciada_em": None, "concluida_em": None,
            "ultima_atividade_em": None,
        }
        for i, nome in enumerate(fases_nomes, 1):
            fid = uid()
            status = "disponivel" if chave == "problema" and i == 1 else "bloqueada"
            DB["progresso_fases"][fid] = {
                "id": fid, "progresso_chave_id": pid,
                "numero_fase": i, "nome_fase": nome,
                "status": status, "conteudo": None, "concluida_em": None,
            }

def _progresso(equipe_id: str, chave: str) -> Optional[dict]:
    return next(
        (p for p in DB["progresso_chaves"].values()
         if p["equipe_id"] == equipe_id and p["chave"] == chave),
        None,
    )

def _fases(progresso_id: str) -> list:
    return sorted(
        [f for f in DB["progresso_fases"].values()
         if f["progresso_chave_id"] == progresso_id],
        key=lambda f: f["numero_fase"],
    )

def _liberar_chaves_livres(equipe_id: str):
    """Após Problema concluída → libera Solução, Parcerias e Oportunidades."""
    for chave in CHAVES_LIVRES:
        prog = _progresso(equipe_id, chave)
        if prog and prog["status"] == "nao_iniciada":
            fases = _fases(prog["id"])
            if fases and fases[0]["status"] == "bloqueada":
                fases[0]["status"] = "disponivel"

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
    description="API pedagógica · UFLA · v1.2.0",
    version="1.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────
# ROTAS — AUTH
# ─────────────────────────────────────────────────────────
@app.post("/auth/cadastro", tags=["Auth"])
def cadastrar(dados: UsuarioCriar):
    """Cadastra educador e retorna token JWT."""
    if any(u["email"] == dados.email.lower() for u in DB["usuarios"].values()):
        raise HTTPException(409, "E-mail já cadastrado.")
    usuario = {
        "id": uid(), "nome": dados.nome, "sobrenome": dados.sobrenome,
        "email": dados.email.lower(), "instituicao": dados.instituicao,
        "perfil": "educador", "senha_hash": hash_senha(dados.senha),
        "criado_em": agora(),
    }
    DB["usuarios"][usuario["id"]] = usuario
    token = criar_token({"sub": usuario["id"], "perfil": "educador"})
    return {
        "access_token": token,
        "usuario": {k: v for k, v in usuario.items() if k != "senha_hash"},
    }


@app.post("/auth/login", tags=["Auth"])
def login(dados: LoginEntrada):
    """Login com e-mail e senha."""
    usuario = next(
        (u for u in DB["usuarios"].values() if u["email"] == dados.email.lower()),
        None,
    )
    if not usuario or not verificar_senha(dados.senha, usuario["senha_hash"]):
        raise HTTPException(401, "E-mail ou senha incorretos.")
    token = criar_token({"sub": usuario["id"], "perfil": usuario["perfil"]})
    return {
        "access_token": token,
        "usuario": {k: v for k, v in usuario.items() if k != "senha_hash"},
    }


@app.get("/auth/me", tags=["Auth"])
def meu_perfil(edu=Depends(get_educador)):
    """Perfil do educador autenticado."""
    return {k: v for k, v in edu.items() if k != "senha_hash"}


# ─────────────────────────────────────────────────────────
# ROTAS — SESSÃO
# ─────────────────────────────────────────────────────────
@app.post("/sessao", tags=["Sessão"])
def criar_sessao(dados: SessaoCriar, edu=Depends(get_educador)):
    """Cria sessão e gera equipes automaticamente."""
    if not (1 <= dados.num_equipes <= 10):
        raise HTTPException(400, "Número de equipes deve ser entre 1 e 10.")
    while True:
        codigo = gerar_codigo()
        if not any(s["codigo_acesso"] == codigo for s in DB["sessoes"].values()):
            break
    sid = uid()
    sessao = {
        "id": sid, "educador_id": edu["id"],
        "titulo": dados.titulo, "contexto": dados.contexto,
        "cenario": dados.cenario, "codigo_acesso": codigo,
        "status": "aguardando", "criada_em": agora(), "iniciada_em": None,
    }
    DB["sessoes"][sid] = sessao
    equipes = []
    for n in range(1, dados.num_equipes + 1):
        eid = uid()
        DB["equipes"][eid] = {"id": eid, "sessao_id": sid,
                               "nome": f"Equipe {n}", "numero": n}
        _inicializar_progressos(eid)
        equipes.append({"id": eid, "nome": f"Equipe {n}"})
    return {**sessao, "equipes": equipes}


@app.get("/sessao", tags=["Sessão"])
def listar_sessoes(edu=Depends(get_educador)):
    """Lista sessões do educador."""
    sessoes = [s for s in DB["sessoes"].values()
               if s["educador_id"] == edu["id"]]
    return sorted(sessoes, key=lambda s: s["criada_em"], reverse=True)


@app.get("/sessao/{sessao_id}", tags=["Sessão"])
def detalhar_sessao(sessao_id: str, edu=Depends(get_educador)):
    """Detalhes da sessão com equipes e progresso."""
    sessao = DB["sessoes"].get(sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    equipes = sorted(
        [e for e in DB["equipes"].values() if e["sessao_id"] == sessao_id],
        key=lambda e: e["numero"],
    )
    resultado = []
    for eq in equipes:
        chaves = resumo_chaves(eq["id"])
        concluidas = sum(1 for v in chaves.values() if v["status"] == "concluida")
        resultado.append({**eq, "chaves": chaves, "chaves_concluidas": concluidas})
    alertas = [a for a in DB["alertas"].values()
               if a.get("sessao_id") == sessao_id and not a.get("resolvido")]
    return {**sessao, "equipes": resultado, "alertas": alertas}


@app.patch("/sessao/{sessao_id}/acao", tags=["Sessão"])
def acao_sessao(sessao_id: str, dados: SessaoAcao, edu=Depends(get_educador)):
    """Controla o ciclo: iniciar · pausar · retomar · socializar · encerrar."""
    sessao = DB["sessoes"].get(sessao_id)
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
    sessao["status"] = destino
    if dados.acao == "iniciar":
        sessao["iniciada_em"] = agora()
    return sessao


# ─────────────────────────────────────────────────────────
# ROTAS — JOGADOR
# ─────────────────────────────────────────────────────────
@app.post("/entrar", tags=["Jogador"])
def entrar_com_codigo(dados: EntrarComCodigo):
    """Jogador entra pelo código — sem cadastro."""
    sessao = next(
        (s for s in DB["sessoes"].values()
         if s["codigo_acesso"] == dados.codigo.upper()),
        None,
    )
    if not sessao:
        raise HTTPException(404, "Código de sessão inválido.")
    if sessao["status"] not in ("aguardando", "ativa"):
        raise HTTPException(400, "Sessão não está aceitando participantes.")
    equipe = next(
        (e for e in DB["equipes"].values()
         if e["sessao_id"] == sessao["id"] and e["numero"] == dados.numero_equipe),
        None,
    )
    if not equipe:
        raise HTTPException(404, f"Equipe {dados.numero_equipe} não encontrada.")
    pid = uid()
    DB["participantes"][pid] = {
        "id": pid, "equipe_id": equipe["id"],
        "nome": dados.nome, "entrou_em": agora(),
    }
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
    """Estado das 4 chaves e 12 fases de uma equipe."""
    if not DB["equipes"].get(equipe_id):
        raise HTTPException(404, "Equipe não encontrada.")
    return resumo_chaves(equipe_id)


@app.post("/chaves/{equipe_id}/ativar", tags=["Chaves"])
def ativar_chave(equipe_id: str, dados: AtivarChave,
                 payload=Depends(get_usuario_atual)):
    """
    Ativa uma chave.
    Problema: sempre disponível.
    Solução / Parcerias / Oportunidades: requerem Problema concluída.
    Após Problema concluída, as três ficam disponíveis simultaneamente.
    """
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
    prog["status"] = "ativa"
    prog["iniciada_em"] = prog["iniciada_em"] or agora()
    prog["ultima_atividade_em"] = agora()
    fases = _fases(prog["id"])
    if fases and fases[0]["status"] == "bloqueada":
        fases[0]["status"] = "disponivel"
    return resumo_chaves(equipe_id)[chave]


@app.post("/chaves/{equipe_id}/concluir-fase", tags=["Chaves"])
def concluir_fase(equipe_id: str, dados: ConcluirFase,
                  payload=Depends(get_usuario_atual)):
    """
    Conclui uma fase e libera a próxima.
    Fase 3 de Problema → libera Solução, Parcerias e Oportunidades simultaneamente.
    """
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
    fase["status"] = "concluida"
    fase["conteudo"] = dados.conteudo
    fase["concluida_em"] = agora()
    prog["ultima_atividade_em"] = agora()
    proxima = next(
        (f for f in fases if f["numero_fase"] == dados.numero_fase + 1), None
    )
    if proxima:
        proxima["status"] = "disponivel"
    else:
        prog["status"] = "concluida"
        prog["concluida_em"] = agora()
        if chave == "problema":
            _liberar_chaves_livres(equipe_id)
    return {
        "fase_concluida": {"numero": fase["numero_fase"], "nome": fase["nome_fase"]},
        "chave_status": prog["status"],
        "chaves_atualizadas": resumo_chaves(equipe_id),
    }


# ─────────────────────────────────────────────────────────
# ROTAS — ALERTAS
# ─────────────────────────────────────────────────────────
@app.post("/alertas/{sessao_id}/verificar", tags=["Alertas"])
def verificar_alertas(sessao_id: str, edu=Depends(get_educador)):
    """Verifica e retorna novos alertas de mediação."""
    sessao = DB["sessoes"].get(sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    equipes = [e for e in DB["equipes"].values() if e["sessao_id"] == sessao_id]
    novos = []
    contagens = {
        eq["id"]: sum(
            1 for p in DB["progresso_chaves"].values()
            if p["equipe_id"] == eq["id"] and p["status"] == "concluida"
        )
        for eq in equipes
    }
    if contagens:
        max_c = max(contagens.values())
        media = sum(contagens.values()) / len(contagens)
        if max_c >= 2 and max_c > media + 1:
            lider_id = max(contagens, key=lambda k: contagens[k])
            ja_existe = any(
                a.get("tipo") == "equipe_avancada"
                and a.get("equipe_id") == lider_id
                and not a.get("resolvido")
                for a in DB["alertas"].values()
            )
            if not ja_existe:
                lider = DB["equipes"][lider_id]
                aid = uid()
                alerta = {
                    "id": aid, "sessao_id": sessao_id, "equipe_id": lider_id,
                    "tipo": "equipe_avancada",
                    "mensagem": f"{lider['nome']} está mais avançada ({max_c} chaves).",
                    "sugestao": f"Peça à {lider['nome']} que compartilhe o raciocínio.",
                    "resolvido": False, "criado_em": agora(),
                }
                DB["alertas"][aid] = alerta
                novos.append(alerta)
    return {"novos_alertas": novos, "total": len(novos)}


@app.patch("/alertas/{alerta_id}/resolver", tags=["Alertas"])
def resolver_alerta(alerta_id: str, edu=Depends(get_educador)):
    """Marca alerta como resolvido."""
    alerta = DB["alertas"].get(alerta_id)
    if not alerta:
        raise HTTPException(404, "Alerta não encontrado.")
    alerta["resolvido"] = True
    alerta["resolvido_em"] = agora()
    return alerta


# ─────────────────────────────────────────────────────────
# ROTAS — SOCIALIZAÇÃO / PITCH
# ─────────────────────────────────────────────────────────
@app.get("/pitch/{sessao_id}", tags=["Socialização"])
def pitch_sessao(sessao_id: str, payload=Depends(get_usuario_atual)):
    """Mural de pitch consolidado de todas as equipes."""
    sessao = DB["sessoes"].get(sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")
    equipes = sorted(
        [e for e in DB["equipes"].values() if e["sessao_id"] == sessao_id],
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
    p = DB["participantes"].get(pid)
    return p["nome"] if p else "Desconhecido"

def _validar_equipe_participante(equipe_id: str, participante_id: str):
    if not DB["equipes"].get(equipe_id):
        raise HTTPException(404, "Equipe não encontrada.")
    p = DB["participantes"].get(participante_id)
    if not p:
        raise HTTPException(404, "Participante não encontrado.")
    if p["equipe_id"] != equipe_id:
        raise HTTPException(403, "Participante não pertence a esta equipe.")


@app.post("/comunicacao/cutucar", tags=["Comunicacao"])
def cutucar(dados: CutucarEntrada, payload=Depends(get_usuario_atual)):
    """① Cutucar membro parado — notificação discreta, sem texto."""
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
    DB["cutucar"][cid] = registro
    return {"ok": True,
            "mensagem": f"{registro['de_nome']} cutucou {registro['para_nome']}."}


@app.get("/comunicacao/cutucar/{equipe_id}/{participante_id}", tags=["Comunicacao"])
def ver_cutucar(equipe_id: str, participante_id: str,
                payload=Depends(get_usuario_atual)):
    """Cutucares não lidos — exibe notificação piscante."""
    pendentes = [
        c for c in DB["cutucar"].values()
        if c["equipe_id"] == equipe_id
        and c["para_id"] == participante_id and not c["lido"]
    ]
    return {"pendentes": len(pendentes), "cutucares": pendentes}


@app.patch("/comunicacao/cutucar/{cutucar_id}/lido", tags=["Comunicacao"])
def marcar_cutucar_lido(cutucar_id: str, payload=Depends(get_usuario_atual)):
    """Remove a notificação piscante."""
    c = DB["cutucar"].get(cutucar_id)
    if not c:
        raise HTTPException(404, "Cutucar não encontrado.")
    c["lido"] = True
    return {"ok": True}


@app.post("/comunicacao/sussurro", tags=["Comunicacao"])
def enviar_sussurro(dados: SussurroEntrada, payload=Depends(get_usuario_atual)):
    """② Mensagem privada — só o destinatário lê. Educador vê que aconteceu."""
    _validar_equipe_participante(dados.equipe_id, dados.de_participante_id)
    _validar_equipe_participante(dados.equipe_id, dados.para_participante_id)
    if dados.de_participante_id == dados.para_participante_id:
        raise HTTPException(400, "Não é possível enviar sussurro para si mesmo.")
    if not dados.mensagem.strip():
        raise HTTPException(400, "Mensagem vazia.")
    sid = uid()
    DB["sussurros"][sid] = {
        "id": sid, "tipo": "sussurro", "equipe_id": dados.equipe_id,
        "de_id": dados.de_participante_id,
        "de_nome": _nome_participante(dados.de_participante_id),
        "para_id": dados.para_participante_id,
        "para_nome": _nome_participante(dados.para_participante_id),
        "mensagem": dados.mensagem.strip(),
        "lido": False, "criado_em": agora(),
    }
    return {"ok": True, "id": sid}


@app.get("/comunicacao/sussurro/{equipe_id}/{participante_id}", tags=["Comunicacao"])
def ver_sussurros(equipe_id: str, participante_id: str,
                  payload=Depends(get_usuario_atual)):
    """Sussurros recebidos pelo participante."""
    recebidos = sorted(
        [s for s in DB["sussurros"].values()
         if s["equipe_id"] == equipe_id and s["para_id"] == participante_id],
        key=lambda s: s["criado_em"],
    )
    return {"total": len(recebidos), "sussurros": recebidos}


@app.post("/comunicacao/balao", tags=["Comunicacao"])
def enviar_balao(dados: BalaoColetivo, payload=Depends(get_usuario_atual)):
    """③ Balão coletivo — mensagem visível para toda a equipe."""
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
    DB["baloes_coletivos"][bid] = registro
    return {"ok": True, "registro": registro}


@app.get("/comunicacao/balao/{equipe_id}", tags=["Comunicacao"])
def ver_baloes(equipe_id: str, payload=Depends(get_usuario_atual)):
    """Todos os balões coletivos em ordem cronológica."""
    baloes = sorted(
        [b for b in DB["baloes_coletivos"].values()
         if b["equipe_id"] == equipe_id],
        key=lambda b: b["criado_em"],
    )
    return {"total": len(baloes), "baloes": baloes}


@app.get("/comunicacao/registro/{equipe_id}", tags=["Comunicacao"])
def chat_registro(equipe_id: str, payload=Depends(get_usuario_atual)):
    """④ Histórico completo — cutucares, sussurros (sem conteúdo) e balões."""
    sub = payload.get("sub", "")
    eventos = []
    for c in DB["cutucar"].values():
        if c["equipe_id"] == equipe_id:
            eventos.append({
                "tipo": "cutucar",
                "descricao": f"{c['de_nome']} cutucou {c['para_nome']}",
                "conteudo": None, "criado_em": c["criado_em"],
            })
    for s in DB["sussurros"].values():
        if s["equipe_id"] == equipe_id:
            e_participante = sub in (s["de_id"], s["para_id"])
            eventos.append({
                "tipo": "sussurro",
                "descricao": f"{s['de_nome']} → {s['para_nome']} (sussurro)",
                "conteudo": s["mensagem"] if e_participante else None,
                "criado_em": s["criado_em"],
            })
    for b in DB["baloes_coletivos"].values():
        if b["equipe_id"] == equipe_id:
            eventos.append({
                "tipo": "balao_coletivo",
                "descricao": b["mensagem"],
                "conteudo": b["mensagem"], "criado_em": b["criado_em"],
            })
    eventos.sort(key=lambda e: e["criado_em"])
    return {"total": len(eventos), "eventos": eventos}


# ─────────────────────────────────────────────────────────
# ROTAS — NOVAS FUNÇÕES ☕
# ─────────────────────────────────────────────────────────
@app.get("/novas-funcoes", tags=["Novas Funcoes ☕"])
def listar_novas_funcoes():
    """☕ Catálogo de funcionalidades planejadas."""
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


@app.post("/novas-funcoes/{funcao_id}/ativar", tags=["Novas Funcoes ☕"])
def ativar_nova_funcao(funcao_id: str, edu=Depends(get_educador)):
    """☕ Reservado — implementado nas próximas versões."""
    raise HTTPException(
        503, {"mensagem": f"'{funcao_id}' em desenvolvimento. Em breve! ☕"}
    )


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

MISSOES_RPG = {
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
             "objetivo": "Descreva os riscos e como a equipe planeja mitiga-los."},
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


@app.get("/rpg/papeis", tags=["RPG"])
def listar_papeis():
    """Quatro papéis narrativos disponíveis no modo RPG."""
    return {"papeis": PAPEIS_RPG}


@app.get("/rpg/cenario/{contexto}", tags=["RPG"])
def buscar_cenario(contexto: str):
    """Cenário narrativo de abertura. Contextos: escolar | gestao | superior."""
    cen = CENARIOS_RPG.get(contexto)
    if not cen:
        raise HTTPException(404, f"Cenário '{contexto}' não encontrado.")
    return {"contexto": contexto, **cen}


@app.post("/rpg/papel", tags=["RPG"])
def registrar_papel(dados: PapelRPGEntrada, payload=Depends(get_usuario_atual)):
    """Registra o papel RPG escolhido por um participante."""
    papel_valido = next((p for p in PAPEIS_RPG if p["id"] == dados.papel_id), None)
    if not papel_valido:
        raise HTTPException(400, f"Papel '{dados.papel_id}' inválido.")
    rid = uid()
    DB["papeis_rpg"][rid] = {
        "id": rid, "participante_id": dados.participante_id,
        "papel_id": dados.papel_id, "papel_nome": dados.papel_nome,
        "papel_icone": dados.papel_icone, "papel_cor": dados.papel_cor,
        "registrado_em": agora(),
    }
    return {"ok": True, "papel": papel_valido}


@app.get("/rpg/papel/{participante_id}", tags=["RPG"])
def buscar_papel_participante(participante_id: str,
                              payload=Depends(get_usuario_atual)):
    """Papel RPG de um participante."""
    papel = next(
        (p for p in DB["papeis_rpg"].values()
         if p["participante_id"] == participante_id),
        None,
    )
    if not papel:
        raise HTTPException(404, "Participante ainda não escolheu um papel.")
    return papel


@app.get("/rpg/equipe/{equipe_id}", tags=["RPG"])
def papeis_da_equipe(equipe_id: str, payload=Depends(get_usuario_atual)):
    """Papéis de todos os participantes de uma equipe."""
    participantes = [p for p in DB["participantes"].values()
                     if p["equipe_id"] == equipe_id]
    resultado = []
    for part in participantes:
        papel = next(
            (r for r in DB["papeis_rpg"].values()
             if r["participante_id"] == part["id"]),
            None,
        )
        resultado.append({"participante_id": part["id"],
                          "nome": part["nome"], "papel": papel})
    return {"equipe_id": equipe_id, "membros": resultado}


@app.get("/rpg/missoes/{chave}", tags=["RPG"])
def missoes_por_chave(chave: str):
    """Missões narrativas (linguagem RPG) de cada fase de uma chave."""
    missoes = MISSOES_RPG.get(chave)
    if not missoes:
        raise HTTPException(404, f"Chave '{chave}' não encontrada.")
    return missoes


# ─────────────────────────────────────────────────────────
# HEALTH CHECK + PÁGINA INICIAL
# ─────────────────────────────────────────────────────────
@app.get("/health", tags=["Sistema"])
def health():
    return {
        "status": "ok", "app": "TdoE", "versao": "1.2.0",
        "usuarios": len(DB["usuarios"]),
        "sessoes":  len(DB["sessoes"]),
        "equipes":  len(DB["equipes"]),
        "comunicacao": {
            "cutucares": len(DB["cutucar"]),
            "sussurros": len(DB["sussurros"]),
            "baloes":    len(DB["baloes_coletivos"]),
        },
        "rpg": {
            "papeis_disponiveis":  len(PAPEIS_RPG),
            "cenarios_disponiveis": len(CENARIOS_RPG),
            "papeis_registrados":  len(DB["papeis_rpg"]),
        },
    }


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def pagina_inicial():
    return """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"/>
<title>TdoE API</title>
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
</style></head><body>
<p style="color:#555;font-size:11px;margin-bottom:6px;">★ TdoE · UFLA</p>
<h1>Tabuleiro do Empreendedor</h1>
<p style="color:#555;font-size:13px;">API pedagógica · v1.2.0 · 32 rotas</p>
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
<div class="card" style="border-color:rgba(240,188,64,.2);background:rgba(240,188,64,.03);">
  <h3 style="color:#F0BC40">☕ Novas funções</h3>
  <div class="r" style="border-color:rgba(240,188,64,.12);">
    <span class="m" style="background:rgba(240,188,64,.2);color:#F0BC40;">GET</span>/novas-funcoes
    <div class="d">Desafios · Coringas · Cartas (em breve)</div>
  </div>
</div>
</div>
<div class="cta">
  <a href="/docs" class="btn b1">📖 Documentação interativa →</a>
  <a href="/health" class="btn b2">✓ Health check</a>
</div>
</body></html>"""


# ─────────────────────────────────────────────────────────
# INICIALIZAÇÃO — COMPATÍVEL COM SPYDER E TERMINAL
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    # Render.com injeta PORT; localmente usa 8000
    env_port = int(os.environ.get("PORT", 0))
    porta = env_port if env_port else porta_livre(8000)
    host  = "0.0.0.0" if env_port else "127.0.0.1"
    print()
    print("  ★  TdoE — Tabuleiro do Empreendedor  v1.2.0")
    print("  ─────────────────────────────────────────────")
    print(f"  Interface:     http://localhost:{porta}")
    print(f"  Documentação:  http://localhost:{porta}/docs")
    print(f"  Health:        http://localhost:{porta}/health")
    print()
    print("  Módulos: Auth · Sessão · Chaves · Alertas · Pitch")
    print("           Comunicação · Novas funções ☕ · RPG 🎮")
    print()
    print("  Pressione Ctrl+C para parar.")
    print()
    uvicorn.run(
        app,
        host=host,
        port=porta,
        reload=False,
        log_level="warning",
    )
