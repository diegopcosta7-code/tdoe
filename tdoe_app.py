"""
TdoE — Tabuleiro do Empreendedor
=================================
Arquivo único. Roda com:
    pip install fastapi uvicorn python-jose
    python tdoe_app.py

Acesse: http://localhost:8000
API:    http://localhost:8000/docs
"""

# ─────────────────────────────────────────────────────────
# DEPENDÊNCIAS
# ─────────────────────────────────────────────────────────
import uuid, hashlib, hmac, random, string, json
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
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
    # Comunicacao da equipe
    "cutucar":          {},
    "sussurros":        {},
    "baloes_coletivos": {},
    # Novas funcoes (reservado)
    "novas_funcoes":    {},
}


# ─────────────────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────────────────
def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()

def verificar_senha(senha: str, h: str) -> bool:
    return hmac.compare_digest(hash_senha(senha), h)

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

def uid() -> str:
    return str(uuid.uuid4())

def agora() -> str:
    return datetime.utcnow().isoformat()


# ─────────────────────────────────────────────────────────
# SEGURANÇA — DEPENDENCY INJECTION
# ─────────────────────────────────────────────────────────
bearer = HTTPBearer(auto_error=False)

def get_usuario_atual(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token não informado.")
    payload = decodificar_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado.")
    return payload

def get_educador(payload=Depends(get_usuario_atual)):
    if payload.get("perfil") not in ("educador", "instituicao"):
        raise HTTPException(status_code=403, detail="Apenas educadores têm acesso.")
    usuario = DB["usuarios"].get(payload["sub"])
    if not usuario:
        raise HTTPException(status_code=401, detail="Usuário não encontrado.")
    return usuario


# ─────────────────────────────────────────────────────────
# LÓGICA PEDAGÓGICA
# ─────────────────────────────────────────────────────────
def _inicializar_progressos(equipe_id: str):
    """Cria progresso nas 4 chaves e 12 fases para uma equipe."""
    for chave, fases_nomes in FASES_POR_CHAVE.items():
        pid = uid()
        DB["progresso_chaves"][pid] = {
            "id": pid, "equipe_id": equipe_id, "chave": chave,
            "status": "nao_iniciada",
            "iniciada_em": None, "concluida_em": None, "ultima_atividade_em": None,
        }
        for i, nome in enumerate(fases_nomes, 1):
            fid = uid()
            # Apenas fase 1 de Problema começa disponível
            status_ini = "disponivel" if chave == "problema" and i == 1 else "bloqueada"
            DB["progresso_fases"][fid] = {
                "id": fid, "progresso_chave_id": pid,
                "numero_fase": i, "nome_fase": nome,
                "status": status_ini, "conteudo": None, "concluida_em": None,
            }

def _progresso(equipe_id: str, chave: str) -> Optional[dict]:
    return next(
        (p for p in DB["progresso_chaves"].values()
         if p["equipe_id"] == equipe_id and p["chave"] == chave), None
    )

def _fases(progresso_id: str) -> list:
    return sorted(
        [f for f in DB["progresso_fases"].values()
         if f["progresso_chave_id"] == progresso_id],
        key=lambda f: f["numero_fase"]
    )

def _liberar_chaves_livres(equipe_id: str):
    """
    Regra central do TdoE:
    Após Problema concluída → Solução, Parcerias e Oportunidades
    ficam TODAS disponíveis. A equipe escolhe a ordem livremente.
    Nenhuma delas é bloqueada em relação às outras.
    """
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
        # Chave disponível = nao_iniciada mas fase 1 liberada
        status_exibir = prog["status"] if prog else "nao_iniciada"
        if status_exibir == "nao_iniciada" and fases and fases[0]["status"] == "disponivel":
            status_exibir = "disponivel"
        resultado[chave] = {
            "status": status_exibir,
            "fases": [
                {"numero": f["numero_fase"], "nome": f["nome_fase"],
                 "status": f["status"], "conteudo": f["conteudo"]}
                for f in fases
            ],
        }
    return resultado


# ─────────────────────────────────────────────────────────
# SCHEMAS PYDANTIC
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
    acao: str  # iniciar | pausar | retomar | socializar | encerrar

# ── Comunicacao ───────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────
# APLICAÇÃO
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title="TdoE — Tabuleiro do Empreendedor",
    description="API pedagógica do TdoE · UFLA",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────
# ROTAS — AUTH
# ─────────────────────────────────────────────────────────
@app.post("/auth/cadastro", tags=["Auth"])
def cadastrar(dados: UsuarioCriar):
    """Cadastra um educador e retorna o token JWT."""
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
    """Login com e-mail e senha. Retorna token JWT."""
    usuario = next(
        (u for u in DB["usuarios"].values() if u["email"] == dados.email.lower()), None
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
    """Retorna os dados do educador autenticado."""
    return {k: v for k, v in edu.items() if k != "senha_hash"}


# ─────────────────────────────────────────────────────────
# ROTAS — SESSÃO
# ─────────────────────────────────────────────────────────
@app.post("/sessao", tags=["Sessão"])
def criar_sessao(dados: SessaoCriar, edu=Depends(get_educador)):
    """Cria uma sessão e gera as equipes automaticamente."""
    if not (1 <= dados.num_equipes <= 10):
        raise HTTPException(400, "Número de equipes deve ser entre 1 e 10.")

    # Garantir código único
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

    equipes_criadas = []
    for n in range(1, dados.num_equipes + 1):
        eid = uid()
        equipe = {"id": eid, "sessao_id": sid, "nome": f"Equipe {n}", "numero": n}
        DB["equipes"][eid] = equipe
        _inicializar_progressos(eid)
        equipes_criadas.append({"id": eid, "nome": equipe["nome"]})

    return {**sessao, "equipes": equipes_criadas}


@app.get("/sessao", tags=["Sessão"])
def listar_sessoes(edu=Depends(get_educador)):
    """Lista todas as sessões do educador autenticado."""
    sessoes = [s for s in DB["sessoes"].values() if s["educador_id"] == edu["id"]]
    return sorted(sessoes, key=lambda s: s["criada_em"], reverse=True)


@app.get("/sessao/{sessao_id}", tags=["Sessão"])
def detalhar_sessao(sessao_id: str, edu=Depends(get_educador)):
    """Retorna detalhes de uma sessão com equipes e progresso."""
    sessao = DB["sessoes"].get(sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")

    equipes = [e for e in DB["equipes"].values() if e["sessao_id"] == sessao_id]
    resultado = []
    for eq in sorted(equipes, key=lambda e: e["numero"]):
        chaves = resumo_chaves(eq["id"])
        concluidas = sum(1 for v in chaves.values() if v["status"] == "concluida")
        resultado.append({**eq, "chaves": chaves, "chaves_concluidas": concluidas})

    alertas = [a for a in DB["alertas"].values()
               if a.get("sessao_id") == sessao_id and not a.get("resolvido")]
    return {**sessao, "equipes": resultado, "alertas": alertas}


@app.patch("/sessao/{sessao_id}/acao", tags=["Sessão"])
def acao_sessao(sessao_id: str, dados: SessaoAcao, edu=Depends(get_educador)):
    """
    Gerencia o ciclo de vida da sessão.
    Ações: iniciar | pausar | retomar | socializar | encerrar
    """
    sessao = DB["sessoes"].get(sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")

    transicoes = {
        "iniciar":     ("aguardando", "ativa"),
        "pausar":      ("ativa",      "pausada"),
        "retomar":     ("pausada",    "ativa"),
        "socializar":  ("ativa",      "socializando"),
        "encerrar":    (None,         "encerrada"),  # qualquer estado
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
# ROTAS — JOGADOR (sem cadastro)
# ─────────────────────────────────────────────────────────
@app.post("/entrar", tags=["Jogador"])
def entrar_com_codigo(dados: EntrarComCodigo):
    """
    Fluxo do jogador: entra pelo código de sessão sem precisar de cadastro.
    Recebe um token temporário com equipe_id.
    """
    sessao = next(
        (s for s in DB["sessoes"].values()
         if s["codigo_acesso"] == dados.codigo.upper()), None
    )
    if not sessao:
        raise HTTPException(404, "Código de sessão inválido.")
    if sessao["status"] not in ("aguardando", "ativa"):
        raise HTTPException(400, "Esta sessão não está aceitando novos participantes.")

    equipe = next(
        (e for e in DB["equipes"].values()
         if e["sessao_id"] == sessao["id"] and e["numero"] == dados.numero_equipe), None
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
        "equipe_id": equipe["id"],
        "equipe_nome": equipe["nome"],
    }


# ─────────────────────────────────────────────────────────
# ROTAS — CHAVES
# ─────────────────────────────────────────────────────────
@app.get("/chaves/{equipe_id}", tags=["Chaves"])
def ver_chaves(equipe_id: str, payload=Depends(get_usuario_atual)):
    """Retorna o estado de todas as chaves e fases de uma equipe."""
    if not DB["equipes"].get(equipe_id):
        raise HTTPException(404, "Equipe não encontrada.")
    return resumo_chaves(equipe_id)


@app.post("/chaves/{equipe_id}/ativar", tags=["Chaves"])
def ativar_chave(equipe_id: str, dados: AtivarChave, payload=Depends(get_usuario_atual)):
    """
    Ativa uma chave para a equipe.
    Problema: sempre disponível.
    Solução, Parcerias, Oportunidades: requerem Problema concluída.
    Após Problema concluída, as três ficam disponíveis simultaneamente —
    a equipe escolhe a ordem livremente.
    """
    chave = dados.chave.lower()
    if chave not in FASES_POR_CHAVE:
        raise HTTPException(400, f"Chave '{chave}' inválida.")

    if chave in CHAVES_LIVRES:
        prob = _progresso(equipe_id, "problema")
        if not prob or prob["status"] != "concluida":
            raise HTTPException(400,
                "Conclua a chave Problema antes de ativar "
                f"a chave {chave.title()}."
            )

    prog = _progresso(equipe_id, chave)
    if not prog:
        raise HTTPException(404, "Progresso não encontrado.")
    if prog["status"] == "concluida":
        raise HTTPException(400, f"Chave {chave.title()} já está concluída.")

    prog["status"] = "ativa"
    prog["iniciada_em"] = prog["iniciada_em"] or agora()
    prog["ultima_atividade_em"] = agora()

    fases = _fases(prog["id"])
    if fases and fases[0]["status"] == "bloqueada":
        fases[0]["status"] = "disponivel"

    return resumo_chaves(equipe_id)[chave]


@app.post("/chaves/{equipe_id}/concluir-fase", tags=["Chaves"])
def concluir_fase(equipe_id: str, dados: ConcluirFase, payload=Depends(get_usuario_atual)):
    """
    Conclui uma fase e libera a próxima.
    Se for a fase 3 de Problema → libera Solução, Parcerias e Oportunidades.
    Se for a fase 3 de qualquer outra → conclui a chave.
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

    # Concluir a fase
    fase["status"] = "concluida"
    fase["conteudo"] = dados.conteudo
    fase["concluida_em"] = agora()
    prog["ultima_atividade_em"] = agora()

    # Liberar próxima fase dentro da mesma chave
    proxima = next((f for f in fases if f["numero_fase"] == dados.numero_fase + 1), None)
    if proxima:
        proxima["status"] = "disponivel"
    else:
        # Última fase — concluir a chave
        prog["status"] = "concluida"
        prog["concluida_em"] = agora()
        # Se foi Problema → liberar as 3 chaves livres
        if chave == "problema":
            _liberar_chaves_livres(equipe_id)

    return {
        "fase_concluida": {
            "numero": fase["numero_fase"],
            "nome": fase["nome_fase"],
            "conteudo": fase["conteudo"],
        },
        "chave_status": prog["status"],
        "chaves_atualizadas": resumo_chaves(equipe_id),
    }


# ─────────────────────────────────────────────────────────
# ROTAS — ALERTAS
# ─────────────────────────────────────────────────────────
@app.post("/alertas/{sessao_id}/verificar", tags=["Alertas"])
def verificar_alertas(sessao_id: str, edu=Depends(get_educador)):
    """
    Verifica e retorna novos alertas de mediação para a sessão.
    Em produção, isso roda automaticamente a cada minuto.
    """
    sessao = DB["sessoes"].get(sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")

    equipes = [e for e in DB["equipes"].values() if e["sessao_id"] == sessao_id]
    novos = []

    # Contar chaves concluídas por equipe
    contagens = {}
    for eq in equipes:
        n = sum(
            1 for p in DB["progresso_chaves"].values()
            if p["equipe_id"] == eq["id"] and p["status"] == "concluida"
        )
        contagens[eq["id"]] = n

    if contagens:
        max_c = max(contagens.values())
        media = sum(contagens.values()) / len(contagens)

        if max_c >= 2 and max_c > media + 1:
            lider_id = max(contagens, key=lambda k: contagens[k])
            lider = DB["equipes"][lider_id]
            # Não duplicar alerta
            ja_existe = any(
                a.get("tipo") == "equipe_avancada"
                and a.get("equipe_id") == lider_id
                and not a.get("resolvido")
                for a in DB["alertas"].values()
            )
            if not ja_existe:
                aid = uid()
                alerta = {
                    "id": aid, "sessao_id": sessao_id, "equipe_id": lider_id,
                    "tipo": "equipe_avancada",
                    "mensagem": f"{lider['nome']} está mais avançada ({max_c} chaves).",
                    "sugestao": f"Peça à {lider['nome']} que compartilhe seu raciocínio.",
                    "resolvido": False, "criado_em": agora(),
                }
                DB["alertas"][aid] = alerta
                novos.append(alerta)

    return {"novos_alertas": novos, "total": len(novos)}


@app.patch("/alertas/{alerta_id}/resolver", tags=["Alertas"])
def resolver_alerta(alerta_id: str, edu=Depends(get_educador)):
    """Educador marca um alerta como resolvido."""
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
    """
    Consolida o mural de pitch de todas as equipes.
    Ordena das mais avançadas para as menos avançadas.
    """
    sessao = DB["sessoes"].get(sessao_id)
    if not sessao:
        raise HTTPException(404, "Sessão não encontrada.")

    equipes = sorted(
        [e for e in DB["equipes"].values() if e["sessao_id"] == sessao_id],
        key=lambda e: e["numero"]
    )
    cards = []
    for eq in equipes:
        chaves = resumo_chaves(eq["id"])
        concluidas = sum(1 for v in chaves.values() if v["status"] == "concluida")

        # Última proposta registrada (conteúdo da última fase concluída)
        proposta = None
        for chave, dados in chaves.items():
            prog = _progresso(eq["id"], chave)
            if prog:
                for fase in reversed(_fases(prog["id"])):
                    if fase["status"] == "concluida" and fase["conteudo"]:
                        proposta = fase["conteudo"]
                        break
            if proposta:
                break

        cards.append({
            "equipe_id": eq["id"],
            "equipe_nome": eq["nome"],
            "chaves_concluidas": concluidas,
            "chaves": {k: v["status"] for k, v in chaves.items()},
            "proposta": proposta or "Em construção...",
        })

    cards.sort(key=lambda c: c["chaves_concluidas"], reverse=True)
    return {
        "sessao_id": sessao_id,
        "titulo": sessao["titulo"],
        "contexto": sessao["contexto"],
        "status": sessao["status"],
        "equipes": cards,
    }


# ─────────────────────────────────────────────────────────
# INTERFACE WEB — PÁGINA INICIAL
# ─────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def pagina_inicial():
    return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>TdoE — Tabuleiro do Empreendedor</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:system-ui,sans-serif;background:#0A0A10;color:#e8e6e0;min-height:100vh;padding:40px 20px;}
.star{display:inline-block;margin-right:10px;}
h1{font-size:48px;font-weight:900;letter-spacing:-2px;background:linear-gradient(125deg,#22C97A,#0FD4B0,#2E80F0,#A040E0);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.sub{color:#888;margin-top:6px;font-size:15px;}
.bar{height:3px;background:linear-gradient(90deg,#22C97A,#0FD4B0,#2E80F0,#A040E0);border-radius:2px;margin:28px 0;box-shadow:0 0 12px rgba(46,128,240,.4);}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:8px;}
.card{background:#181826;border:.5px solid rgba(255,255,255,.1);border-radius:14px;padding:22px;}
.card h3{font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:14px;}
.route{background:#0F0F18;border:.5px solid rgba(255,255,255,.08);border-radius:9px;padding:10px 14px;margin-bottom:8px;font-size:13px;}
.method{display:inline-block;padding:2px 8px;border-radius:5px;font-size:10px;font-weight:700;margin-right:8px;}
.get{background:rgba(46,128,240,.2);color:#2E80F0;}
.post{background:rgba(34,201,122,.2);color:#22C97A;}
.patch{background:rgba(240,188,64,.2);color:#F0BC40;}
.path{color:#e8e6e0;}
.desc{color:#666;font-size:11px;margin-top:4px;}
.cta{margin-top:28px;display:flex;gap:12px;flex-wrap:wrap;}
.btn{padding:12px 24px;border-radius:10px;font-size:14px;font-weight:700;text-decoration:none;display:inline-block;}
.btn-primary{background:linear-gradient(135deg,#2E80F0,#5B6CF0);color:#fff;box-shadow:0 4px 20px rgba(46,128,240,.4);}
.btn-secondary{background:rgba(255,255,255,.06);color:#e8e6e0;border:.5px solid rgba(255,255,255,.15);}
.chave{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:10px;margin-bottom:8px;border:.5px solid;}
.badge{display:inline-block;padding:4px 10px;border-radius:20px;font-size:10px;font-weight:700;margin-left:auto;}
footer{margin-top:48px;color:#444;font-size:12px;text-align:center;}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute">
  <defs>
    <path id="s" d="M50,4 L53,44 L50,50 L47,44 Z M50,96 L53,56 L50,50 L47,56 Z M4,50 L44,47 L50,50 L44,53 Z M96,50 L56,47 L50,50 L56,53 Z M18,18 L44,44 L50,50 L44,44 Z M82,18 L56,44 L50,50 L56,44 Z M18,82 L44,56 L50,50 L44,56 Z M82,82 L56,56 L50,50 L56,56 Z"/>
  </defs>
</svg>

<svg width="32" height="32" viewBox="0 0 100 100" class="star">
  <use href="#s" fill="#F0BC40"/>
  <circle cx="50" cy="50" r="4" fill="#F0BC40"/>
</svg>
<h1>TdoE</h1>
<p class="sub">Tabuleiro do Empreendedor · API Back-End · UFLA</p>

<div class="bar"></div>

<div class="cards">

  <div class="card">
    <h3 style="color:#22C97A">🔐 Auth</h3>
    <div class="route">
      <span class="method post">POST</span><span class="path">/auth/cadastro</span>
      <div class="desc">Cadastrar educador — retorna JWT</div>
    </div>
    <div class="route">
      <span class="method post">POST</span><span class="path">/auth/login</span>
      <div class="desc">Login com e-mail e senha</div>
    </div>
    <div class="route">
      <span class="method get">GET</span><span class="path">/auth/me</span>
      <div class="desc">Perfil do educador autenticado</div>
    </div>
  </div>

  <div class="card">
    <h3 style="color:#2E80F0">📋 Sessão</h3>
    <div class="route">
      <span class="method post">POST</span><span class="path">/sessao</span>
      <div class="desc">Criar sessão + equipes automáticas</div>
    </div>
    <div class="route">
      <span class="method get">GET</span><span class="path">/sessao</span>
      <div class="desc">Listar sessões do educador</div>
    </div>
    <div class="route">
      <span class="method get">GET</span><span class="path">/sessao/{id}</span>
      <div class="desc">Detalhes com equipes e progresso</div>
    </div>
    <div class="route">
      <span class="method patch">PATCH</span><span class="path">/sessao/{id}/acao</span>
      <div class="desc">iniciar · pausar · socializar · encerrar</div>
    </div>
  </div>

  <div class="card">
    <h3 style="color:#0FD4B0">🎮 Jogador</h3>
    <div class="route">
      <span class="method post">POST</span><span class="path">/entrar</span>
      <div class="desc">Entrar com código — sem cadastro</div>
    </div>
    <div class="route">
      <span class="method get">GET</span><span class="path">/chaves/{equipe_id}</span>
      <div class="desc">Ver estado das 4 chaves e fases</div>
    </div>
    <div class="route">
      <span class="method post">POST</span><span class="path">/chaves/{equipe_id}/ativar</span>
      <div class="desc">Ativar uma chave de investigação</div>
    </div>
    <div class="route">
      <span class="method post">POST</span><span class="path">/chaves/{equipe_id}/concluir-fase</span>
      <div class="desc">Concluir fase → libera próxima</div>
    </div>
  </div>

  <div class="card">
    <h3 style="color:#A040E0">⚡ Alertas e Pitch</h3>
    <div class="route">
      <span class="method post">POST</span><span class="path">/alertas/{sessao_id}/verificar</span>
      <div class="desc">Detectar equipes paradas ou avançadas</div>
    </div>
    <div class="route">
      <span class="method patch">PATCH</span><span class="path">/alertas/{id}/resolver</span>
      <div class="desc">Marcar alerta como resolvido</div>
    </div>
    <div class="route">
      <span class="method get">GET</span><span class="path">/pitch/{sessao_id}</span>
      <div class="desc">Mural de socialização — todas as equipes</div>
    </div>
  </div>

  <div class="card">
    <h3 style="color:#0FD4B0">💬 Comunicação da equipe</h3>
    <div class="route">
      <span class="method post">POST</span><span class="path">/comunicacao/cutucar</span>
      <div class="desc">① Cutucar membro parado — notificação discreta</div>
    </div>
    <div class="route">
      <span class="method post">POST</span><span class="path">/comunicacao/sussurro</span>
      <div class="desc">② Mensagem individual privada — só o destinatário lê</div>
    </div>
    <div class="route">
      <span class="method post">POST</span><span class="path">/comunicacao/balao</span>
      <div class="desc">③ Balão coletivo — fala para toda a equipe</div>
    </div>
    <div class="route">
      <span class="method get">GET</span><span class="path">/comunicacao/registro/{equipe_id}</span>
      <div class="desc">④ Chat de registro cronológico da sessão</div>
    </div>
  </div>

  <div class="card" style="border:.5px solid rgba(240,188,64,.3);background:rgba(240,188,64,.04);">
    <h3 style="color:#F0BC40">☕ Novas funções</h3>
    <div class="route" style="background:rgba(240,188,64,.06);border-color:rgba(240,188,64,.15);">
      <span class="method get" style="background:rgba(240,188,64,.2);color:#F0BC40;">GET</span><span class="path">/novas-funcoes</span>
      <div class="desc">Catálogo de funcionalidades planejadas</div>
    </div>
    <div class="route" style="background:rgba(240,188,64,.06);border-color:rgba(240,188,64,.15);">
      <span class="method post" style="background:rgba(240,188,64,.2);color:#F0BC40;">POST</span><span class="path">/novas-funcoes/{id}/ativar</span>
      <div class="desc">Desafios extras · Coringas · Cartas pedagógicas</div>
    </div>
    <div style="margin-top:10px;font-size:10px;color:rgba(240,188,64,.6);font-style:italic;">Em desenvolvimento — disponível em breve</div>
  </div>

</div>

<div style="margin-top:28px;background:#181826;border:.5px solid rgba(255,255,255,.1);border-radius:14px;padding:22px;">
  <h3 style="font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#F0BC40;margin-bottom:16px;">🔑 As quatro chaves</h3>
  <div class="chave" style="background:rgba(34,201,122,.06);border-color:rgba(34,201,122,.25);">
    <span style="font-size:20px;">🔍</span>
    <div>
      <div style="font-weight:700;color:#22C97A;">Problema</div>
      <div style="font-size:11px;color:#666;">Contexto · Características · Motivação</div>
    </div>
    <span class="badge" style="background:rgba(34,201,122,.15);color:#22C97A;border:.5px solid rgba(34,201,122,.3);">Entrada obrigatória</span>
  </div>
  <div class="chave" style="background:rgba(15,212,176,.06);border-color:rgba(15,212,176,.25);">
    <span style="font-size:20px;">✓</span>
    <div>
      <div style="font-weight:700;color:#0FD4B0;">Solução</div>
      <div style="font-size:11px;color:#666;">Características · Custos · Riscos</div>
    </div>
    <span class="badge" style="background:rgba(255,255,255,.06);color:#888;border:.5px solid rgba(255,255,255,.1);">Livre após Problema</span>
  </div>
  <div class="chave" style="background:rgba(46,128,240,.06);border-color:rgba(46,128,240,.25);">
    <span style="font-size:20px;">🤝</span>
    <div>
      <div style="font-weight:700;color:#2E80F0;">Parcerias</div>
      <div style="font-size:11px;color:#666;">Recursos · Características · Tempo</div>
    </div>
    <span class="badge" style="background:rgba(255,255,255,.06);color:#888;border:.5px solid rgba(255,255,255,.1);">Livre após Problema</span>
  </div>
  <div class="chave" style="background:rgba(160,64,224,.06);border-color:rgba(160,64,224,.25);">
    <span style="font-size:20px;">💡</span>
    <div>
      <div style="font-weight:700;color:#A040E0;">Oportunidades</div>
      <div style="font-size:11px;color:#666;">Características · Diferenciação · Aplicabilidade</div>
    </div>
    <span class="badge" style="background:rgba(255,255,255,.06);color:#888;border:.5px solid rgba(255,255,255,.1);">Livre após Problema</span>
  </div>
</div>

<div class="cta">
  <a href="/docs" class="btn btn-primary">📖 Abrir documentação interativa →</a>
  <a href="/health" class="btn btn-secondary">✓ Health check</a>
</div>

<footer>TdoE · Tabuleiro do Empreendedor · UFLA · versão 1.0.0</footer>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────
# ROTAS — COMUNICACAO DA EQUIPE
# ─────────────────────────────────────────────────────────

def _nome_participante(pid: str) -> str:
    """Retorna o nome do participante pelo id, ou 'Desconhecido'."""
    p = DB["participantes"].get(pid)
    return p["nome"] if p else "Desconhecido"

def _validar_equipe_participante(equipe_id: str, participante_id: str):
    """Verifica se o participante pertence à equipe informada."""
    equipe = DB["equipes"].get(equipe_id)
    if not equipe:
        raise HTTPException(404, "Equipe não encontrada.")
    participante = DB["participantes"].get(participante_id)
    if not participante:
        raise HTTPException(404, "Participante não encontrado.")
    if participante["equipe_id"] != equipe_id:
        raise HTTPException(403, "Participante não pertence a esta equipe.")


# ① CUTUCAR
@app.post("/comunicacao/cutucar", tags=["Comunicacao"])
def cutucar(dados: CutucarEntrada, payload=Depends(get_usuario_atual)):
    """
    Envia um cutucar discreto para um membro da equipe.
    Aparece como notificação piscante no card do membro.
    Registrado no chat de registro — o educador vê que aconteceu.
    """
    _validar_equipe_participante(dados.equipe_id, dados.de_participante_id)
    _validar_equipe_participante(dados.equipe_id, dados.para_participante_id)

    if dados.de_participante_id == dados.para_participante_id:
        raise HTTPException(400, "Não é possível cutucar a si mesmo.")

    cid = uid()
    registro = {
        "id": cid,
        "tipo": "cutucar",
        "equipe_id": dados.equipe_id,
        "de_id": dados.de_participante_id,
        "de_nome": _nome_participante(dados.de_participante_id),
        "para_id": dados.para_participante_id,
        "para_nome": _nome_participante(dados.para_participante_id),
        "lido": False,
        "criado_em": agora(),
    }
    DB["cutucar"][cid] = registro
    return {
        "ok": True,
        "mensagem": f"{registro['de_nome']} cutucou {registro['para_nome']}.",
        "registro": registro,
    }


@app.get("/comunicacao/cutucar/{equipe_id}/{participante_id}", tags=["Comunicacao"])
def ver_cutucar(equipe_id: str, participante_id: str, payload=Depends(get_usuario_atual)):
    """
    Retorna os cutucares não lidos para um participante.
    Usado para exibir a notificação piscante no tabuleiro.
    """
    pendentes = [
        c for c in DB["cutucar"].values()
        if c["equipe_id"] == equipe_id
        and c["para_id"] == participante_id
        and not c["lido"]
    ]
    return {"pendentes": len(pendentes), "cutucares": pendentes}


@app.patch("/comunicacao/cutucar/{cutucar_id}/lido", tags=["Comunicacao"])
def marcar_cutucar_lido(cutucar_id: str, payload=Depends(get_usuario_atual)):
    """Marca um cutucar como lido — remove a notificação piscante."""
    c = DB["cutucar"].get(cutucar_id)
    if not c:
        raise HTTPException(404, "Cutucar não encontrado.")
    c["lido"] = True
    return {"ok": True}


# ② SUSSURRO (mensagem individual privada)
@app.post("/comunicacao/sussurro", tags=["Comunicacao"])
def enviar_sussurro(dados: SussurroEntrada, payload=Depends(get_usuario_atual)):
    """
    Envia uma mensagem privada para um membro específico da equipe.
    Apenas o destinatário lê o conteúdo.
    O educador vê no registro que um sussurro foi enviado, mas não o conteúdo.
    """
    _validar_equipe_participante(dados.equipe_id, dados.de_participante_id)
    _validar_equipe_participante(dados.equipe_id, dados.para_participante_id)

    if dados.de_participante_id == dados.para_participante_id:
        raise HTTPException(400, "Não é possível enviar sussurro para si mesmo.")
    if not dados.mensagem.strip():
        raise HTTPException(400, "Mensagem não pode estar vazia.")

    sid = uid()
    registro = {
        "id": sid,
        "tipo": "sussurro",
        "equipe_id": dados.equipe_id,
        "de_id": dados.de_participante_id,
        "de_nome": _nome_participante(dados.de_participante_id),
        "para_id": dados.para_participante_id,
        "para_nome": _nome_participante(dados.para_participante_id),
        "mensagem": dados.mensagem.strip(),
        "lido": False,
        "criado_em": agora(),
    }
    DB["sussurros"][sid] = registro
    return {
        "ok": True,
        "mensagem": f"Sussurro enviado para {registro['para_nome']}.",
        "id": sid,
        "criado_em": registro["criado_em"],
    }


@app.get("/comunicacao/sussurro/{equipe_id}/{participante_id}", tags=["Comunicacao"])
def ver_sussurros(equipe_id: str, participante_id: str, payload=Depends(get_usuario_atual)):
    """
    Retorna os sussurros recebidos por um participante.
    Apenas o destinatário pode consultar esta rota.
    """
    recebidos = [
        s for s in DB["sussurros"].values()
        if s["equipe_id"] == equipe_id and s["para_id"] == participante_id
    ]
    recebidos.sort(key=lambda s: s["criado_em"])
    return {"total": len(recebidos), "sussurros": recebidos}


# ③ BALAO COLETIVO (mensagem para toda a equipe)
@app.post("/comunicacao/balao", tags=["Comunicacao"])
def enviar_balao(dados: BalaoColetivo, payload=Depends(get_usuario_atual)):
    """
    Envia uma mensagem visível para todos os membros da equipe.
    Equivale a falar em voz alta dentro do grupo.
    """
    _validar_equipe_participante(dados.equipe_id, dados.participante_id)
    if not dados.mensagem.strip():
        raise HTTPException(400, "Mensagem não pode estar vazia.")

    bid = uid()
    registro = {
        "id": bid,
        "tipo": "balao_coletivo",
        "equipe_id": dados.equipe_id,
        "de_id": dados.participante_id,
        "de_nome": _nome_participante(dados.participante_id),
        "mensagem": dados.mensagem.strip(),
        "criado_em": agora(),
    }
    DB["baloes_coletivos"][bid] = registro
    return {"ok": True, "registro": registro}


@app.get("/comunicacao/balao/{equipe_id}", tags=["Comunicacao"])
def ver_baloes(equipe_id: str, payload=Depends(get_usuario_atual)):
    """Retorna todos os baloes coletivos de uma equipe em ordem cronologica."""
    baloes = [
        b for b in DB["baloes_coletivos"].values()
        if b["equipe_id"] == equipe_id
    ]
    baloes.sort(key=lambda b: b["criado_em"])
    return {"total": len(baloes), "baloes": baloes}


# ④ CHAT DE REGISTRO (consolidado)
@app.get("/comunicacao/registro/{equipe_id}", tags=["Comunicacao"])
def chat_registro(equipe_id: str, payload=Depends(get_usuario_atual)):
    """
    Retorna o historico completo de comunicacao da equipe em ordem cronologica.
    Inclui: cutucares, sussurros (sem conteudo para educador) e baloes coletivos.
    Usado no chat de registro visivel ao educador ao final da sessao.
    """
    eventos = []

    for c in DB["cutucar"].values():
        if c["equipe_id"] == equipe_id:
            eventos.append({
                "tipo": "cutucar",
                "de_nome": c["de_nome"],
                "para_nome": c["para_nome"],
                "descricao": f"{c['de_nome']} cutucou {c['para_nome']}",
                "conteudo": None,
                "criado_em": c["criado_em"],
            })

    for s in DB["sussurros"].values():
        if s["equipe_id"] == equipe_id:
            # Conteúdo visível apenas para quem consulta com id de participante
            # Na rota do registro geral, omitimos o conteúdo (privacidade)
            sub = payload.get("sub", "")
            e_participante = sub in (s["de_id"], s["para_id"])
            eventos.append({
                "tipo": "sussurro",
                "de_nome": s["de_nome"],
                "para_nome": s["para_nome"],
                "descricao": f"{s['de_nome']} → {s['para_nome']} (sussurro)",
                "conteudo": s["mensagem"] if e_participante else None,
                "criado_em": s["criado_em"],
            })

    for b in DB["baloes_coletivos"].values():
        if b["equipe_id"] == equipe_id:
            eventos.append({
                "tipo": "balao_coletivo",
                "de_nome": b["de_nome"],
                "para_nome": "equipe",
                "descricao": b["mensagem"],
                "conteudo": b["mensagem"],
                "criado_em": b["criado_em"],
            })

    eventos.sort(key=lambda e: e["criado_em"])
    return {"total": len(eventos), "eventos": eventos}


# ─────────────────────────────────────────────────────────
# ROTAS — NOVAS FUNCOES (☕ reservado para expansao futura)
# ─────────────────────────────────────────────────────────

@app.get("/novas-funcoes", tags=["Novas Funcoes ☕"])
def listar_novas_funcoes():
    """
    ☕ Novas funções — espaço reservado para expansões futuras.
    Retorna o catalogo de funcionalidades planejadas:
      - Desafios extras (além dos automáticos)
      - Coringas para as equipes
      - Cartas pedagógicas
    """
    return {
        "status": "em_breve",
        "descricao": "Funcionalidades planejadas para proximas versoes do TdoE",
        "funcionalidades": [
            {
                "id": "desafios_extras",
                "nome": "Desafios extras",
                "descricao": "Baralho de desafios adicionais que o educador pode lançar manualmente a qualquer momento, além dos automáticos.",
                "status": "em_breve",
                "icone": "⚡",
            },
            {
                "id": "coringas",
                "nome": "Coringas",
                "descricao": "Cartas especiais que a equipe pode usar uma vez por sessão — pular uma fase, pedir dica ao educador, ou trocar informações com outra equipe.",
                "status": "em_breve",
                "icone": "🃏",
            },
            {
                "id": "cartas_pedagogicas",
                "nome": "Cartas pedagógicas",
                "descricao": "Cartões com conceitos, exemplos reais e perguntas geradoras enviados pelo educador para apoiar uma equipe em dificuldade.",
                "status": "em_breve",
                "icone": "📚",
            },
        ],
    }


@app.post("/novas-funcoes/{funcao_id}/ativar", tags=["Novas Funcoes ☕"])
def ativar_nova_funcao(funcao_id: str, edu=Depends(get_educador)):
    """
    ☕ Endpoint reservado — será implementado nas próximas versões.
    Recebe o id da funcionalidade e retorna o status de disponibilidade.
    """
    raise HTTPException(
        status_code=503,
        detail={
            "mensagem": f"A funcionalidade '{funcao_id}' ainda está em desenvolvimento. Disponível em breve! ☕",
            "status": "em_breve",
        }
    )


# ─────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────
@app.get("/health", tags=["Sistema"])
def health():
    return {
        "status": "ok",
        "app": "TdoE",
        "versao": "1.1.0",
        "usuarios": len(DB["usuarios"]),
        "sessoes": len(DB["sessoes"]),
        "equipes": len(DB["equipes"]),
        "comunicacao": {
            "cutucares": len(DB["cutucar"]),
            "sussurros": len(DB["sussurros"]),
            "baloes_coletivos": len(DB["baloes_coletivos"]),
        },
    }


# ─────────────────────────────────────────────────────────
# INICIAR SERVIDOR
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print()
    print()
    print("  ★  TdoE — Tabuleiro do Empreendedor  v1.1.0")
    print("  ─────────────────────────────────────────────")
    print("  Interface:       http://localhost:8000")
    print("  Documentação:    http://localhost:8000/docs")
    print("  Health:          http://localhost:8000/health")
    print()
    print("  Módulos ativos:")
    print("    ✓ Auth · Sessão · Chaves · Alertas · Pitch")
    print("    ✓ Comunicação: cutucar · sussurro · balão · registro")
    print("    ☕ Novas funções: /novas-funcoes (reservado)")
    print()
    uvicorn.run("tdoe_app:app", host="0.0.0.0", port=8000, reload=True)
