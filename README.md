# TdoE — Tabuleiro do Empreendedor

Jogo pedagógico sério para educação empreendedora, desenvolvido na **UFLA** por:

- **Daniela Meirelles Andrade** — Co-autora
- **Diego Pereira Costa** — Co-autor

Aplicável em EJA, Graduação e Pós-Graduação.

---

## Estrutura do repositório

```
tdoe/
├── tdoe_frontend.html   # Aplicação completa (frontend single-file)
├── run.py               # Servidor local de desenvolvimento
└── README.md
```

---

## Como executar

### Pré-requisitos

- Python 3.8 ou superior (sem dependências externas)

### Iniciar

```bash
python run.py
```

O navegador abre automaticamente em `http://localhost:8000/tdoe_frontend.html`.

### Opções

```bash
python run.py --port 5000      # Usar outra porta
python run.py --no-browser     # Não abrir o navegador automaticamente
```

---

## Funcionalidades

| Tela | Recurso |
|------|---------|
| Login | Conceitos das chaves com referências acadêmicas |
| Login | Criação de equipe / código de acesso |
| Educador | Painel de sessões e equipes |
| Educador | Relatório de interação (imprimível) |
| Educador | Exportação de propostas (modelo de negócios) |
| Jogador | 4 chaves × 3 fases com ícone `?` de apoio |
| Jogador | Chat equipe / individual / registro |
| Ambas | Seletor de idioma: 🇧🇷 PT · 🇺🇸 EN · 🇪🇸 ES |

---

## Contexto acadêmico

As quatro chaves do jogo — **Problema**, **Solução**, **Parcerias** e **Oportunidades** — são baseadas em:

- Landry, 1995 — metodologia de Design Science
- Bianchi; Verganti, 2021 — inovação orientada ao significado
- Hevner et al., 2004 — pesquisa em sistemas de informação

---

## Licença

Uso acadêmico e educacional — UFLA.
