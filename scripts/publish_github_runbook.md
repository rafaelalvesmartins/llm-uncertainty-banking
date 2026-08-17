# Runbook — Publicação do `llm-uncertainty-banking` no GitHub

**Para:** Rafael Martins Alves (peticionário)
**Escopo:** GitHub apenas — **sem PyPI** (decisão D-02)
**Requisito coberto:** EVID-01 (Fase 1 — Evidências e Dependências Externas)
**Criado:** 2026-08-17

---

## Por que este runbook existe

A publicação do repositório é **ato do peticionário**, não do agente: exige credenciais
GitHub e uma decisão sobre o histórico do repositório. Este documento entrega os comandos
exatos a executar; a verificação do resultado é automatizada por
`05_Exhibits_Planejados/_tools/check_github_repo.py`.

**Não use `scripts/go_public.sh` para esta publicação.** Aquele script é de um plano
anterior e está fora do escopo atual em três pontos: inclui etapas de PyPI (contraria D-02),
usa um slug de repositório com erro de digitação, e fixa a versão em `0.0.1` em vez de
`v0.1.0` (contraria D-04). Ele permanece no repositório apenas como registro histórico.

## Decisões travadas que este runbook implementa

| ID | Decisão |
|----|---------|
| D-01 | Publicar a pasta `llm-uncertainty-banking/` **como está** — sem refatoração, limpeza de código ou feature nova. Publicar é empacotar, não construir. |
| D-02 | **GitHub apenas, sem PyPI.** |
| D-03 | O Exhibit D-05 captura snapshot do commit (hash + data ISO) + screenshot da página do repo. |
| D-04 | Criar tag de release **`v0.1.0`**; o snapshot D-05 aponta para ela. |
| D-05 | Repositório **público** — o oficial do USCIS precisa conseguir verificar a evidência. |

## Pré-requisitos

- Conta GitHub `rafaelalvesmartins` (id 10361115) com 2FA ativo.
- `git` instalado — verificado na máquina: **2.51.0**.
- `gh` CLI — **ausente na máquina** na data deste runbook (Passo 1 instala).
- O repositório `llm-uncertainty-banking` **ainda não existe** no GitHub (a API retorna 404).
  Isso é o estado esperado antes da execução.

---

## Passo 0 — DECISÕES PRÉVIAS ✅ RESOLVIDAS (2026-08-17)

As duas decisões bloqueantes foram tomadas pelo peticionário. Ficam registradas aqui.

### Decisão 0.a — Histórico do repositório: **OPÇÃO A (init novo)** ✅

Repositório novo, um commit inicial, sem histórico herdado.

**Fundamentação registrada:**

- A pasta `06_Projeto_GitHub/llm-uncertainty-banking/` **não tem `.git` próprio** — é
  subdiretório do monorepo. `git log -- 06_Projeto_GitHub/llm-uncertainty-banking` retorna
  **3 commits**; o caminho antigo `09_Projeto_GitHub/` tem **767**. Um subtree split do
  caminho atual descartaria essencialmente todo o histórico — ou seja, a opção B **não
  entregaria** a preservação que a justificaria.
- O histórico do monorepo **contém documentos da petição**. Preservá-lo criaria risco de
  exposição pública de material que não deve ser público.
- A evidência do D-05 é a **tag `v0.1.0` e o snapshot do repositório**. Nenhum requisito da
  petição depende da profundidade do histórico.

### Decisão 0.b — Higiene mínima: **AUTORIZADA, com condição de processo** ✅

**Já aplicado pelo agente** (commit registrado no `01-02-SUMMARY.md`):

- `CITATION.cff`: placeholder `orcid: TODO-FILL-BEFORE-PUBLIC-RELEASE` removido (campo
  suprimido — o CFF é válido sem ele e nenhum ORCID real foi fornecido); URLs
  `TODO-FILL-USERNAME` substituídas por `rafaelalvesmartins`; bloco de comentário interno
  que citava e-mails a UNICAMP/BRB removido.
- Arquivo lixo de 0 bytes `'` removido. Os arquivos `py.typed` e `__init__.py` foram
  preservados — são estruturais.

**Condição de processo — menções ao BRB:** nenhuma menção foi removida ou editada. Em vez
disso foi produzido um **inventário de decisão** classificando cada ocorrência:

> 📋 **[`BRB_MENTIONS_DECISION_INVENTORY.md`](BRB_MENTIONS_DECISION_INVENTORY.md)**

O peticionário revisa esse inventário antes de qualquer remoção de conteúdo. Remoção de
menções à afiliação é decisão dele, com o inventário à vista — não de um agente.

⚠️ **O inventário contém dois achados que precisam de decisão antes do commit inicial:**
trechos que afirmam que o trabalho "was supported by" / "conducted under my affiliation
with" o banco (tensionam a C-14 ¶7), e dois worksheets com **detalhe operacional interno do
BRB** (arquitetura de IA do banco) que não deveriam ir para um repositório público.

---

## Passo 1 — Instalar e autenticar o `gh` CLI

```bash
winget install --id GitHub.cli
```

Feche e reabra o terminal para que o `gh` entre no PATH, depois:

```bash
gh auth login
```

Escolha: **GitHub.com** → **HTTPS** → autenticar pelo navegador. Confirme a conta:

```bash
gh auth status
```

A saída deve mostrar `Logged in to github.com account rafaelalvesmartins`.

---

## Passo 2 — Higiene mínima pré-publicação (Decisão 0.b: AUTORIZADA)

> **Estado:** parcialmente aplicado. As correções do `CITATION.cff` e a remoção do arquivo
> lixo **já foram feitas pelo agente** (ver 2.b e 2.c). O que resta é a **sua decisão sobre
> as menções ao BRB** (2.a), que nenhum agente deve tomar.

Isto **não é refatoração de código**: nenhum comportamento do software muda. São dois itens
de credibilidade e um arquivo lixo.

### 2.a — Pré-flight: varredura de vazamento BRB

Antes de qualquer coisa, veja o que será exposto:

```bash
cd "06_Projeto_GitHub/llm-uncertainty-banking"
grep -rl "BRB\|Banco de Bras" . --exclude-dir=.git
grep -rniE "bradesco|itau|santander" . --exclude-dir=.git
grep -rniE "@brb\.|brb\.com\.br|internal|proprietary|confidential" . --exclude-dir=.git
```

**Resultado real em 2026-08-17: 20 arquivos retornam** — dos quais 2 são artefatos de
processo (este runbook e o inventário), logo **19 arquivos de conteúdo**.

> **Correção de um número.** Uma versão anterior deste runbook dizia **16** arquivos. Estava
> errado: o padrão usado (`\bBRB\b`, com fronteira de palavra) não casa com `BRB-internal`
> nem com `BRB's`. Use o `grep -rl "BRB\|Banco de Bras"` acima, que é o padrão correto.

**A classificação completa, arquivo a arquivo, com o trecho citado e a ação recomendada,
está em:**

> 📋 **[`BRB_MENTIONS_DECISION_INVENTORY.md`](BRB_MENTIONS_DECISION_INVENTORY.md)**

O inventário separa as 19 ocorrências em três baldes: afiliação acadêmica normal (manter),
documento interno que não deveria ser público (excluir do commit inicial), e trechos que
tensionam a C-14 ¶7 (decisão crítica). Nem toda menção é problema — três delas são
*protetivas*, afirmando a ausência de conteúdo do banco.

**Ação:** leia o inventário e decida. Este runbook não pré-decide por você — o julgamento
sobre o que é afiliação legítima e o que é ambiguidade indesejada é do peticionário.
**Nenhuma menção ao BRB foi removida ou editada pelo agente.**

### 2.b — `CITATION.cff` ✅ APLICADO

- `orcid: "https://orcid.org/TODO-FILL-BEFORE-PUBLIC-RELEASE"` — **campo removido.** Nenhum
  ORCID real foi fornecido, e o CFF é válido sem ele. Se quiser incluí-lo depois, basta
  acrescentar `orcid:` sob o autor.
- `repository-code` e `url` — `TODO-FILL-USERNAME` **substituído** por `rafaelalvesmartins`.
- Bloco de comentário `# TODO(rafael): ...` que citava e-mails a UNICAMP/BRB e um arquivo
  interno de planejamento — **removido**.
- `affiliation: "Banco de Brasília"` — **intocado**; é item 15 do inventário (balde 1).

Verificado após a edição: nenhum `TODO-FILL` resta no arquivo e o YAML continua válido.

### 2.c — Arquivo lixo ✅ APLICADO

O arquivo de 0 bytes cujo nome é uma aspa simples (`'`, criado em 2026-08-13) foi
**removido**. Ele era untracked, portanto não gerou commit.

**Não remova outros arquivos de 0 bytes.** `src/lub/py.typed`, `src/lub/agents/py.typed`,
`tests/unit/__init__.py` e os `__init__.py` sob `src/lub/connectors/bridge/` são vazios **por
design** — são marcadores de pacote Python e de tipagem. Apagá-los quebra o import do
pacote. Verificado que os três seguem intactos após a remoção. Os arquivos `dict[str` e
`See` mencionados na pesquisa da fase **não existem** neste diretório.

---

## Passo 3 — Preparar o repositório git local

Execute a partir da pasta do lub:

```bash
cd "06_Projeto_GitHub/llm-uncertainty-banking"
```

**Decisão 0.a = opção A (init novo).** Histórico limpo, um commit inicial.

Antes do `git init`, aplique as decisões que você tomou sobre o inventário BRB — em
particular, os caminhos do **balde 2** (documentos internos) que não devem entrar no
repositório público. Com init novo isso é trivial: basta **não adicioná-los ao commit**.
Uma forma de fazer isso é criar o `.gitignore` antes do `git add`, por exemplo:

```bash
cd "06_Projeto_GitHub/llm-uncertainty-banking"

# Exemplo — ajuste conforme SUA decisão sobre o inventário:
cat >> .gitignore <<'EOF'
DESIGN_DECISIONS_PERSONALIZATION_WORKSHEET.md
DESIGN_DECISIONS_OUTLINE.md
planning/
EOF
```

Depois:

```bash
git init
git add .
git status                      # CONFIRA o que será publicado antes de commitar
git commit -m "Initial public release of llm-uncertainty-banking v0.1.0"
```

⚠️ **O `git status` antes do commit não é opcional.** É a última chance de ver, arquivo a
arquivo, o que cruza a fronteira para o público — e, com init novo, o commit inicial é a
única barreira: uma vez publicado, remover um arquivo em commit posterior **não o apaga do
histórico público**.

Confirme especificamente que os worksheets não estão na lista:

```bash
git status --short | grep -i "DESIGN_DECISIONS\|planning/" || echo "OK — worksheets fora do commit"
```

---

## Passo 4 — Criar o repositório público no GitHub (D-05)

```bash
gh repo create llm-uncertainty-banking --public --source . --push
```

Isso cria `https://github.com/rafaelalvesmartins/llm-uncertainty-banking`, adiciona o remote
`origin` e envia a branch atual.

Confirme a visibilidade:

```bash
gh repo view rafaelalvesmartins/llm-uncertainty-banking --json name,visibility,url
```

O campo `visibility` deve ser `PUBLIC`. Repositório privado **não serve como evidência** —
o oficial do USCIS precisa conseguir abrir a página.

---

## Passo 5 — Tag de release `v0.1.0` (D-04)

```bash
git tag v0.1.0
git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --notes "Initial public release"
```

A versão `0.1.0` coincide com `version` no `pyproject.toml` e no `CITATION.cff` do repositório.

---

## Passo 6 — Capturar o snapshot do Exhibit D-05 (D-03)

Ainda na pasta do lub, com a tag já criada:

```bash
git rev-parse v0.1.0                 # hash do commit
git log -1 --format=%cI v0.1.0       # data em ISO 8601
```

Anote os dois valores. Eles são o conteúdo textual do Exhibit D-05.

Falta ainda o **screenshot datado** da página do repositório (D-03): abra
`https://github.com/rafaelalvesmartins/llm-uncertainty-banking` e capture a tela mostrando
o nome do repositório, o badge `Public` e a tag `v0.1.0`.

---

## Passo 7 — Verificação automatizada

Da raiz do monorepo:

```bash
python 05_Exhibits_Planejados/_tools/check_github_repo.py
```

- **Exit 0** — repositório público e tag `v0.1.0` confirmados pela API do GitHub. EVID-01
  verificado.
- **Exit 1** — algo falhou; a mensagem `FAIL:` diz o quê (repositório ausente, privado, ou
  tag ausente).

O script consulta a API pública do GitHub — nenhuma credencial é necessária, e é exatamente
a mesma visão que um terceiro (o oficial do USCIS) teria.

---

## Passo 8 — Efeitos a jusante (não são deste runbook, mas dependem dele)

Depois de `check_github_repo.py` sair 0, ficam destravadas — na **Fase 2** — as seguintes
atualizações de texto:

1. **Reverter a linguagem developmental** na Petition Letter e no Professional Plan: o
   repositório deixa de ser "em desenvolvimento" e passa a ser publicado e verificável.
2. **Corrigir a menção a PyPI** na PL/PP e no **¶8 da C-14** (que hoje diz "GitHub and
   PyPI") para GitHub apenas — D-02.
3. **Registrar o Exhibit D-05** com hash, data ISO e screenshot.

**Enquanto o Passo 7 não sair 0, nenhum documento do pacote pode afirmar que o repositório
está publicado.** A regra do dossiê é que nenhuma afirmação exceda a evidência, e a única
prova aceitável de publicação é a resposta da API do GitHub.

---

## URL do repositório — placeholder

O repositório **ainda não existe**. A URL abaixo só se torna citável depois que o Passo 7
sair 0:

```
https://github.com/rafaelalvesmartins/llm-uncertainty-banking      [NÃO PUBLICADO — placeholder]
```

Não cite essa URL em nenhum documento do pacote antes da publicação real.

---

## Checklist de execução

- [x] Passo 0 — decisões 0.a (opção A, init novo) e 0.b (higiene autorizada) registradas
- [ ] Passo 1 — `gh auth status` mostra `rafaelalvesmartins`
- [x] Passo 2.b/2.c — `CITATION.cff` corrigido e arquivo lixo removido (agente)
- [ ] **Passo 2.a — inventário BRB revisado e decisões tomadas** ← pendente do peticionário
- [ ] Passo 3 — `.gitignore` ajustado conforme o inventário; `git status` conferido antes do commit
- [ ] Passo 4 — `visibility` = `PUBLIC`
- [ ] Passo 5 — tag `v0.1.0` enviada e release criado
- [ ] Passo 6 — hash e data ISO anotados; screenshot capturado
- [ ] Passo 7 — `check_github_repo.py` sai 0
- [ ] Passo 8 — pendências de texto encaminhadas para a Fase 2
