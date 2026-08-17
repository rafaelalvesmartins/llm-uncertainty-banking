# Bridge — Achados consolidados (testes de console, 5 rodadas)

**Data:** 2026-06-20 · **Branch:** `product/bridge-platform` · **Backend:** FakeBackend (demo, sem LLM real)

Consolidação priorizada de tudo que saiu dos testes ponta-a-ponta do Bridge Console
(`localhost:3002`). Cada item foi **verificado no código/runtime** (cito `arquivo:linha`).
Separado em **(A) bugs técnicos**, **(B) regras de negócio que não fazem sentido** e
**(C) UX/apresentação**. Itens já corrigidos nesta sessão estão marcados ✅ com o commit.

Legenda: ✅ corrigido · 🔴 aberto · severidade BLOCKER/ALTA/MÉDIA/BAIXA.

> **Atualização (2026-06-20, mesma sessão):** os 4 itens que estavam abertos foram corrigidos —
> **B1** `8982e74` (guard decide por classe de risco: saldo→PASSTHROUGH, transferência→FLAG, PEP→ESCALATE);
> **A1+A2+B2** `be64dee` (Settings com refresh ao vivo · "Similarity cache" · intent `account_help`).
> Backend **315 passed**, 16 skipped · ruff/mypy/tsc/eslint limpos. As seções abaixo mantêm a descrição
> original do problema (para contexto do time); a coluna de status acima reflete o estado atual.

---

## Resumo executivo (prioridade)

| # | Achado | Cat. | Sev. | Status |
|---|--------|------|------|--------|
| 1 | Guard decide por **confiança = nº de keywords**, não por risco → PASSTHROUGH inalcançável p/ ops triviais **e** cego ao valor da transação | B | **ALTA** | ✅ `8982e74` (por classe de risco) |
| 2 | UI de Policies/Config não reflete o estado real do backend (sem polling) | A | MÉDIA | ✅ `be64dee` |
| 3 | "Cache semântico" é literal (sinônimo não acerta) | A/C | BAIXA | ✅ `be64dee` (renomeado) |
| 4 | Sem intent de recuperação de senha → cai em `general`→REASK (não é "tratado como ataque") | B | BAIXA | ✅ `be64dee` |
| 5 | ESCALATE de injection/rate-limit não entrava em métricas nem auditoria | A | ALTA | ✅ `768fa00` |
| 6 | PII ecoada em texto claro no corpo da resposta `/query` | A | MÉDIA | ✅ `768fa00` |
| 7 | Guard `_extract_risk_level` casava substrings (follows→LOW, highly→HIGH) | A | BAIXA | ✅ `768fa00` |
| 8 | Suíte flaky por estado compartilhado em `$TMP` (battery accuracy) | A | MÉDIA | ✅ `768fa00` |
| 9 | Flow: pergunta sumia, resultado sem contexto, trail "0ms" | C | MÉDIA | ✅ `86a2e25` |
| 10 | Resíduos PT no trail do pipeline | C | BAIXA | ✅ `64edefa` |

---

## A. Bugs técnicos

### A1 🔴 MÉDIA — UI não reflete o estado real do backend
- **Sintoma:** alterar `threshold`/`cache` via API não muda o que Policies/Config exibem.
- **Causa (verificada):** `frontend/components/console/views/Politicas.tsx:76` faz
  `getJSON("/api/settings")` **uma vez no mount** (`useEffect(..., [])`), sem polling.
  Mudanças fora-de-banda (API direta / outro cliente) só aparecem ao **revisitar a aba**
  (o console remonta a view na troca de aba). Não há staleness permanente, mas não há
  atualização ao vivo — ruim para um painel de governança.
- **Recomendação:** dar poll periódico em `/api/settings` (como outros painéis já fazem)
  ou refetch on focus/visibilitychange. Mostrar `updated_at`/origem do valor.

### A2 🔴 BAIXA — "cache semântico" é literal, não semântico
- **Verificado:** idêntica → hit (sim 1.00); 1 palavra trocada → hit (~0.875); **sinônimo**
  ("quanto é meu saldo" vs "qual o valor do meu saldo") → **miss**. Usa similaridade lexical
  com `similarity_threshold=0.85` (`server.py` `SemanticCache(...)`), não embeddings.
- **Impacto:** baixo (funciona, só não generaliza por intenção). O **nome** promete mais.
- **Recomendação:** renomear para "similarity cache" no demo, **ou** trocar o retriever por
  embeddings se quiser semântica real (mudança maior).

---

## B. Regras de negócio que não fazem sentido

### B1 🔴 ALTA — O guard decide por confiança-de-classificação (nº de keywords), não por risco
Este é o achado de maior impacto. Três sintomas, **uma raiz**.

- **Mecanismo (verificado):**
  - Confiança do intent base = `min(0.6 + 0.15 × nº_keywords, 0.98)` (`core/classifier.py:904`)
    → quantizada em {0.50, 0.75, 0.90, 0.98}.
  - Banda do guard (`core/guard.py:101-107`, threshold padrão 0.70):
    PASSTHROUGH se `conf ≥ threshold+0.15` (=0.85) · FLAG se `≥0.70` · REASK se `≥0.50` · senão ESCALATE.

- **Sintoma 1 — PASSTHROUGH inalcançável para o trivial:** "ver saldo" casa 1 keyword → **0.75**
  → cai em **FLAG** (0.70–0.85), nunca PASSTHROUGH. Toda consulta inofensiva vai para a fila
  de revisão humana, inchando o trabalho dos analistas.
- **Sintoma 2 — inversão de risco (verificado, o mais grave):**
  - "ver o saldo" → conf 0.75 → **FLAG** (vai para revisão)
  - "transferir **R$ 5.000.000** para João" → conf 0.90 → **PASSTHROUGH** (liberado direto)
  - A operação **mais arriscada passa direto** e a **mais inofensiva é barrada** — só porque
    "transferir…para" casou 2 keywords e "saldo" casou 1.
- **Sintoma 3 — cegueira ao valor da transação (verificado):** `apply_guard(confidence, threshold,
  intent, risk_level)` **não recebe o valor**. R$ 10 e R$ 5.000.000 → **mesma decisão**.

- **Recomendações (decisão de produto — não apliquei nada):**
  1. Reduzir a margem de PASSTHROUGH (`+0.15` → `+0.05`) e/ou baixar o threshold padrão, **ou**
  2. Decidir por **intent + risco**, não por contagem de keywords: intents `default_decision`
     já existe no catálogo (`balance` = "by-confidence") — intents claramente seguros poderiam
     ser PASSTHROUGH-elegíveis e ações sensíveis (transfer/pix/loan acima de um valor) FLAG/ESCALATE.
  3. Incorporar **valor da transação** ao guard (limiar por faixa de valor / COAF R$ 10k).
  4. Calibração de confiança contínua em vez de degraus de 0.15.

### B2 🔴 BAIXA — Sem fluxo de recuperação de senha
- **Verificado:** "esqueci minha senha / quero recuperar minha senha" → intent `general`,
  conf **0.5** → **REASK** ("reformule"). **Não** é "tratado como ataque" (não vira
  prompt_leak/privilege_escalation) — a afirmação da rodada anterior **não se reproduz** com
  os fraseados comuns. O problema real: **não existe intent de auto-atendimento de senha/conta**,
  então cai em `general` e o cliente recebe um pedido de reformular, inútil.
- **Recomendação:** adicionar intent `account_help`/`password_reset` com resposta canônica.

---

## C. UX / apresentação

### C1 ✅ `86a2e25` — Flow ficou confuso de usar
- Caixa esvaziava após Inspect → **mantém o texto**; resultado agora ecoa **"Inspected query"**;
  trail mostra o que cada etapa fez (MISS/HIT, regras, PII, tier) em vez de "0ms" uniforme.

### C2 ✅ `64edefa` — Resíduos em português no trail → traduzidos.

### C3 🔴 BAIXA — ver A2 (nome "cache semântico").

---

## Apêndice — Corrigido nesta sessão (com testes de regressão)

| Commit | Conteúdo |
|--------|----------|
| `768fa00` | ESCALATE pré-guard em métricas+auditoria (`_record_short_circuit`); PII-echo mascarado em todas as respostas; guard whole-word risk matching; isolamento de teste (`conftest.py`); testes `test_escalate_persistence.py`, `test_response_pii_echo.py` |
| `86a2e25` | Flow UX (query persiste, eco da pergunta, stage trail informativo) |
| `64edefa` | Tradução dos últimos resíduos PT do pipeline |

**Gate atual:** backend `312 passed, 16 skipped` · `ruff`/`mypy` limpos · frontend `tsc`/`eslint` limpos.

---

### Notas de método
- "ESCALATE de injection não auditado" (rodadas 1–3) **já foi corrigido** (`768fa00`) — não
  está mais aberto, apesar de citado nos resumos anteriores.
- Itens marcados 🔴 ALTA/MÉDIA têm causa-raiz verificada em código; B1 e B2 envolvem
  **decisão de produto** (como calibrar / que intents existir), por isso não apliquei correção.
