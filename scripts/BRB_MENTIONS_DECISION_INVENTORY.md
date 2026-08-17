# Inventário de decisão — menções ao BRB no `llm-uncertainty-banking`

**Para:** Rafael Martins Alves (peticionário)
**Produzido:** 2026-08-17
**Status:** aguardando revisão — **nenhum conteúdo foi removido ou editado com base neste inventário**

---

## Por que este documento existe

O repositório será publicado (decisão 0.a: init novo). Antes disso, é preciso saber
exatamente o que ele diz sobre o Banco de Brasília, porque a **declaração C-14 ¶7** afirma,
sob pena de perjúrio:

> "I have developed, and continue to develop, the lub framework entirely outside the scope of
> my employment at the Bank: on my own time, on my own equipment and infrastructure, under my
> personal GitHub account, and using **no Bank code, no Bank data, and no Bank resources of
> any kind**."

Um repositório público que se apresente como produzido *sob* ou *com recursos do* banco
contradiz essa frase. A contradição não precisa ser real para causar dano: basta ser
aparente para um oficial do USCIS que leia os dois documentos lado a lado.

**Este inventário não decide nada.** Remoção de menções à própria afiliação é exatamente o
tipo de edição que deve ser decidida pelo peticionário, com a evidência à vista. O que segue
é a evidência, classificada.

## Método

```bash
grep -rl "BRB\|Banco de Bras" . --exclude-dir=.git
```

**20 arquivos** retornam. Um deles é `scripts/publish_github_runbook.md` e outro é este
próprio inventário — artefatos de processo que documentam a varredura, não conteúdo do
software. **A superfície real de conteúdo é de 19 arquivos.**

> **Correção de um número que reportei antes.** Em execução anterior deste plano eu registrei
> **16** arquivos. Estava errado: usei `\bBRB\b` com fronteira de palavra, que não casa com
> `BRB-internal` nem com `BRB's`. O número correto é o desta varredura. Os dois arquivos que
> escaparam por esse motivo foram `docs/README_ARXIV.md` e
> `scripts/prepare_arxiv_submission.sh`.

## Os três baldes

| Balde | Significado | Ação típica |
|---|---|---|
| **1 — Afiliação acadêmica normal** | Citar a própria instituição em datasheet/paper/CITATION é legítimo e defensável | Manter |
| **2 — Documento interno de planejamento** | Não deveria estar num repositório público, independentemente do BRB | Excluir do repo público (não editar conteúdo) |
| **3 — Tensiona a C-14 ¶7** | Apresenta o trabalho como produzido *sob* ou *com recursos do* banco | **Crítico** — decisão do peticionário |

---

## Balde 3 — CRÍTICO: tensiona a C-14 ¶7

Estes são os únicos trechos que afirmam positivamente uma relação de **suporte ou
patrocínio** entre o banco e o trabalho. Leia cada um contra a frase "no Bank resources of
any kind".

| # | Arquivo | Linha | Trecho | Por que tensiona |
|---|---|---|---|---|
| 1 | `docs/tech-report/draft.md` | 751 | "This work **was supported by the author's affiliation with Banco de Brasília (BRB)** and..." | "Was supported by" é a afirmação oposta a "no Bank resources of any kind". É o item mais direto do inventário. |
| 2 | `docs/arxiv_submission_template.txt` | 93 | "represents my own research **conducted under my affiliation with** Banco de Brasília and academic..." | "Conducted under my affiliation" situa o trabalho dentro do vínculo empregatício, que a C-14 ¶7 exclui explicitamente ("outside the scope of my employment"). |
| 3 | `scripts/generate_arxiv_email.py` | 89 | "represents my own research **conducted under my affiliation with** Banco de Brasília and academic..." | Mesma frase do item 2 — este script **gera** aquele texto. Corrigir um sem o outro reintroduz o problema na próxima execução. |
| 4 | `docs/tech-report/draft.md` | 9 | "*Banco de Brasília (BRB) · UNICAMP collaborator*" — linha de afiliação do autor no relatório técnico | Fronteiriço com o balde 1. É uma linha de afiliação padrão de paper; o peso vem de estar no mesmo documento que a linha 751. |

**Observação sobre o item 1.** A linha 756 do mesmo arquivo já contém um *disclaimer*: "the
author's and do not represent BRB institutional positions or regulatory opinions". Esse
disclaimer isenta o banco das opiniões, mas **não desfaz** a afirmação de que o trabalho foi
*suportado* pela afiliação. São coisas diferentes, e é a primeira que tensiona a C-14.

**Nota de coerência interna do próprio repositório:** `docs/tech-report/SUBMISSION_CHECKLIST.md`
(linha 84) já instrui o contrário do que o draft faz — "affiliation line is UNICAMP (research)
or 'independent researcher'. BRB affiliation stays in the code's CITATION.cff only". O
repositório, portanto, **já contém a política**; o que falta é o draft obedecê-la.

---

## Balde 2 — Documento interno de planejamento

Estes não são problema de BRB especificamente: são documentos de trabalho interno que
expõem material operacional num repositório público. As menções ao BRB agravam, mas a razão
de excluir existiria de qualquer forma.

| # | Arquivo | Ocorr. | O que contém |
|---|---|---|---|
| 5 | `DESIGN_DECISIONS_PERSONALIZATION_WORKSHEET.md` | 7 | **O item mais sensível do inventário.** Contém detalhe operacional interno do banco: *"BRB uses Azure OpenAI for customer-facing chatbots (blackbox only) but runs Llama-3-8B on-prem for internal credit analysis"* e *"At BRB, our internal data platform had no import discipline — by the time I joined, the ETL layer imported directly from the API layer..."* |
| 6 | `planning/root_archive_2026-07-11/DESIGN_DECISIONS_PERSONALIZATION_WORKSHEET.md` | 7 | **Cópia byte-a-byte idêntica** do item 5 (verificado por `diff`). Excluir um sem o outro não resolve. |
| 7 | `DESIGN_DECISIONS_OUTLINE.md` | 1 | Roteiro de perguntas para redação do relatório |
| 8 | `planning/root_archive_2026-07-11/DESIGN_DECISIONS_OUTLINE.md` | 1 | Cópia arquivada do item 7 |
| 9 | `docs/tech-report/READER_ASK_TEMPLATE.md` | 2 | Instruções internas: "From: Rafael's personal email (not BRB corporate)"; "Do not share a preview to anyone inside BRB before arXiv submission" |
| 10 | `docs/tech-report/SUBMISSION_CHECKLIST.md` | 1 | Checklist interno de submissão ao arXiv |
| 11 | `docs/evidence-dashboard.md` | 1 | Nota interna: "keep BRB-internal language out" |
| 12 | `docs/adr/0011-prefiling-freeze.md` | 1 | ADR sobre congelamento pré-filing; menciona e-mails a UNICAMP/BRB |
| 13 | `scripts/setup_public_repo.sh` | 2 | Checklist que referencia `11_Legal_Acknowledgments/02_Email_BRB_Compliance.md` — caminho de um repositório que não é este |
| 14 | `docs/MARKET_RESEARCH.md` | 1 | Pesquisa de mercado interna |

**Atenção ao item 5/6.** Detalhe de arquitetura interna de um banco ("usa Azure OpenAI para
chatbots, Llama-3-8B on-prem para análise de crédito") publicado num repositório público é
um problema em si — de confidencialidade profissional, independentemente da petição. Estes
dois arquivos merecem decisão antes de qualquer outro item deste inventário.

**Forma da ação recomendada:** excluir do repositório público via `.gitignore` ou não
incluir no commit inicial. Como a decisão 0.a é **init novo**, isto é trivial: basta não
adicionar esses caminhos ao primeiro commit. Não é preciso editar nem reescrever nada.

---

## Balde 1 — Afiliação acadêmica normal (manter)

Citar a própria instituição de vínculo em metadados de citação e em datasheets é prática
acadêmica normal e não contradiz a C-14 ¶7, que fala de **recursos**, não de identidade
profissional do autor.

| # | Arquivo | Linha | Trecho |
|---|---|---|---|
| 15 | `CITATION.cff` | 8 | `affiliation: "Banco de Brasília"` — campo padrão CFF |
| 16 | `src/lub/benchmarks/data/DATASHEET.md` | 26 | "**Rafael Martins Alves** (Banco de Brasilia / UNICAMP), as an original..." |
| 17 | `docs/README_ARXIV.md` | 5 | "**Authors:** Rafael Martins Alves (Banco de Brasília, UNICAMP)" |
| 18 | `scripts/prepare_arxiv_submission.sh` | 66, 101 | Gera as linhas de afiliação dos itens 15 e 17 |
| 19 | `docs/arxiv_submission_template.txt` | 33, 98 | "**Affiliations:** Banco de Brasília (BRB), UNICAMP" |

**Nota de tensão residual:** o `SUBMISSION_CHECKLIST.md` (item 10) diz que a afiliação BRB
deveria ficar **apenas** no `CITATION.cff`. Os itens 16–19 contrariam essa política interna.
Isso não é problema de perjúrio — é inconsistência do repositório consigo mesmo. Vale
decidir junto, mas o risco é de coerência, não jurídico.

### Menções que são *protetivas* (nenhuma ação)

Três ocorrências afirmam a **ausência** de material do banco — reforçam a C-14 ¶7 em vez de
contradizê-la. Devem ser mantidas exatamente como estão:

| Arquivo | Linha | Trecho |
|---|---|---|
| `src/lub/benchmarks/br_regulatory.py` | 13 | "**No BRB-internal or otherwise proprietary content is included.**" |
| `scripts/go_public.sh` | 37, 75 | "Pre-flight audits (BRB leakage...)" — o próprio controle de vazamento |
| `docs/MARKET_RESEARCH.md` | 104 | "Supervises BRB and peers" — BRB citado como *objeto* de regulação, não como patrocinador |

---

## Resumo para decisão

| Balde | Arquivos | Urgência |
|---|---|---|
| **3 — tensiona C-14 ¶7** | 3 arquivos (itens 1–4) | **Alta** — contradiz afirmação sob perjúrio |
| **2 — interno, não deveria ser público** | 10 arquivos (itens 5–14) | **Alta para o item 5/6** (detalhe operacional do banco); média para o resto |
| **1 — afiliação normal** | 5 arquivos (itens 15–19) | Baixa — manter; opcionalmente alinhar ao `SUBMISSION_CHECKLIST` |

### O que o peticionário precisa decidir

1. **Itens 1–3 (balde 3):** reescrever "was supported by / conducted under my affiliation
   with" para linguagem que não afirme patrocínio? Corrigir o item 3 junto com o 2, porque o
   script regenera o texto.
2. **Itens 5–6 (worksheets):** confirmar que ficam **fora** do commit inicial. Recomendação
   forte, mas a decisão é sua.
3. **Itens 7–14:** excluir do repositório público em bloco, ou avaliar um a um?
4. **Itens 15–19 (balde 1):** manter como está, ou alinhar à política do próprio
   `SUBMISSION_CHECKLIST.md` (afiliação BRB só no `CITATION.cff`)?

Enquanto isso não for decidido, o **Passo 2 do runbook permanece parcialmente aberto**: a
higiene do `CITATION.cff` e a remoção do arquivo lixo já foram aplicadas, mas nenhuma menção
ao BRB foi tocada.
