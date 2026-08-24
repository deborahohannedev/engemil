# Documentação Técnica — Sistema Engemil

**Projeto:** Engemil — Sistema de Controle de Estoque/Almoxarifado
**Versão:** MVP — Backend, Frontend e Ambiente de Demonstração
**Data de atualização:** 18 de agosto de 2026
**Responsável pela entrega:** Deborah Ohanne
**Repositórios:** `engemil` (backend) e `engemil-frontend` (frontend), branches `main`/`develop` em ambos

> Este documento substitui e atualiza o "Status de Desenvolvimento" anterior (13/08/2026). A versão de 17/08/2026 foi verificada linha a linha contra o código, mas o commit que a criou (`10a67e6`) ficou **atrás** de 3 commits que já estavam no repositório (edição de Solicitação, fix de encerramento de Inventário, `responsavel_conferencia_nome`) — esta revisão (18/08/2026) reconcilia isso e cobre também os commits do dia seguinte (Reabertura de Solicitação removida, Demanda opcional, saldo total no Dashboard).

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Status de desenvolvimento](#2-status-de-desenvolvimento)
3. [Arquitetura](#3-arquitetura)
4. [Modelo de dados](#4-modelo-de-dados)
5. [Perfis e permissões](#5-perfis-e-permissões)
6. [Regras de negócio críticas](#6-regras-de-negócio-críticas)
7. [Fluxos de trabalho](#7-fluxos-de-trabalho)
8. [Referência de API](#8-referência-de-api)
9. [Frontend — estrutura e padrões](#9-frontend--estrutura-e-padrões)
10. [Deploy e ambientes](#10-deploy-e-ambientes)
11. [Próximos passos técnicos](#11-próximos-passos-técnicos)
12. [Pendências de negócio](#12-pendências-de-negócio-para-reunião-com-o-cliente)
13. [Decisões técnicas fechadas](#13-decisões-técnicas-fechadas-não-reabrir-sem-necessidade)

---

## 1. Visão geral

O Engemil é um sistema de controle de estoque/almoxarifado sob medida para a empresa Engemil (setor elétrico), cobrindo o ciclo completo de um material dentro do estoque:

- **Entrada** de material (compra/recebimento) → confirmação → soma no saldo
- **Solicitação** de material por um posto/demanda → confirmação de saída → subtrai do saldo
- **Devolução** de material solicitado e não usado → aprovação/rejeição → soma de volta (se em condição de uso)
- **Inventário** físico periódico → contagem → ajuste automático de divergência

Toda alteração de saldo de estoque, qualquer que seja a origem, converge para um único registro de auditoria (`Movimentacao`), append-only, que serve tanto de fonte de verdade para o saldo atual (`Material.estoque_real`) quanto de trilha de auditoria completa.

O sistema tem controle de acesso por 6 perfis de usuário (só 3 estão com regras de negócio implementadas hoje — ver [seção 5](#5-perfis-e-permissões)), login por CPF, e senha de primeiro acesso gerada pelo sistema.

---

## 2. Status de desenvolvimento

### ✅ Concluído

**Documentação / Design**
- Modelo entidade-relacionamento (ER) fechado
- Dicionário de dados
- Modelo de classes (DDD: Aggregates, Value Objects, Domain Services)
- Documento de arquitetura ART-04 (Django+DRF, JWT, apps por bounded context)
- Documentação técnica interna viva nos dois repositórios (`ARCHITECTURE.md`, `BUSINESS_RULES.md`, `FLUXOS.md`, `STATE.md`, `TODO.md`) — mantida a cada sessão de desenvolvimento

**Ambiente**
- Python 3.12.7 via pyenv (**nunca** 3.14 — incompatível com Django 5.0.6)
- Django 5.0.6 + dependências fixadas em `requirements.txt`
- PostgreSQL 16 local via Docker (`engemil-db`)
- `config/settings/` dividido em `base.py`/`development.py`/`production.py`
- `django-environ` configurado — `.env` protegido no `.gitignore`
- Node.js 22 + Vite + React + TypeScript para o frontend

**Backend — App `core`**
- `Perfil`, `Posto`, `Usuario` (Custom User Model), `UnidadeMedida`, `ReferenciaTecnica`, `Fornecedor`, `Demanda`, `Material`, `Movimentacao` — models completos
- `AUTH_USER_MODEL = core.Usuario`, login por CPF (`USERNAME_FIELD = 'cpf'`)
- `core/domain/`: `OrigemMovimentacao` (Value Object) + `MovimentacaoService` + `SaldoEstoqueService`
- `UsuarioCreateSerializer` com senha aleatória gerada via `create_user()` (nunca aceita senha do cliente)
- Migrations geradas e aplicadas; banco de dev/prod zerado e recriado do zero nesta sessão (sem dívida de migration pendente)

**Backend — Apps de domínio (`solicitacoes`, `entradas`, `devolucoes`, `inventario`)**
- Todos os 4 apps com `models.py` + `domain/services.py` completos
- `SolicitacaoService` — `separar` (novo, 24/08 — etapa manual item a item, não debita estoque), `marcar_disponivel_para_retirada` (novo, 24/08), `confirmar_saida` (atendimento parcial; só pega itens já `SEPARADO`; aceita `quantidades_senado` opcional — ver "🆕 Novidades" abaixo), `verificar_disponibilidade`, `cancelar`, `reconciliar_status_apos_edicao` (para a edição de cabeçalho/itens, ver seção 6). **`reabrir` foi implementado e depois removido** — ver "🆕 Novidades e 🔥 Removido" logo abaixo
- `EntradaService` — `confirmar`, protegido contra dupla confirmação (`confirmada_em` + `EntradaJaConfirmadaError`)
- `DevolucaoService` — `informar`/`aprovar`/`rejeitar`, com bloqueio RN-010 e proteção contra devolução duplicada/saldo insuficiente em duas camadas
- `InventarioService` — `iniciar`/`registrar_contagem_fisica`/`encerrar`, reformulado numa sessão anterior; `encerrar()` ganhou proteção contra `SaldoInsuficienteError` (ajuste pendente, ver seção 6)

**Backend — Camada `api/`**
- `permissions.py` — `PerfilPermission` (com `funcoes_somente_leitura`), `ApenasProprioSolicitante`, `ApenasDevolucaoDoProprioSolicitante` — **matriz de permissões fechada e implementada** para os 4 perfis com regra definida
- `serializers/` — todos os domínios, padrão leitura + criação separados, `validate()` espelhando os `CheckConstraint` do banco
- `views/` — todas as actions de negócio: `cancelar`, `confirmar-saida`, `disponivel-para-retirada` (novo, 24/08) (Solicitação), `laudo` (Inventário, PDF); `update`/`partial_update` de Solicitação ganharam suporte a edição de cabeçalho+itens (`SolicitacaoEditSerializer`). Novo `ItemSolicitacaoViewSet` (`/itens-solicitacao/<id>/separar/`, 24/08) — só retrieve + `separar`, de propósito não é `ModelViewSet` completo (evita abrir escrita direta em campos que contornariam as validações de criação/edição)
- `views/dashboard.py::DashboardResumoView` (**novo**) — `GET /api/dashboard/resumo/`, fora do `DefaultRouter` (não é um recurso CRUD)
- `urls.py` com `DefaultRouter` + JWT (`auth/token/`, `auth/token/refresh/`) + `dashboard/resumo/`
- `django-cors-headers`, `django-filter`, paginação configurados
- **Busca e filtro em praticamente todos os endpoints de listagem** (concluído nesta sessão — ver [seção 8](#8-referência-de-api))
- `MovimentacaoSerializer` ganhou `usuario_nome`; `select_related` aplicado para evitar N+1

**Backend — Dados e ferramentas**
- `seed_inicial` — popula os 6 perfis + 2 usuários administradores de demonstração
- `seed_teste_perfis` — 4 usuários de teste (1 por perfil ativo) + Posto/Demanda de teste; roda em produção também (ambiente de deploy é MVP/demonstração)
- `importar_materiais` — 978 materiais reais da Engemil importados de planilha Excel (idempotente, `--dry-run` disponível)
- `seed_demo` (**novo**) — dados ricos de demonstração via services de domínio (não inserts crus): fornecedores, entradas, solicitações e devoluções em vários estados, inventários em andamento e encerrado com divergência
- Roteiro de teste manual da API documentado, cobrindo os fluxos de ponta a ponta

**Backend — Inventário (retrabalho completo nesta sessão)**
- `iniciar()` não recebe mais lista de materiais — inclui automaticamente todos os materiais `ATIVO` (⚠️ temporariamente limitado aos 10 primeiros para a demonstração, ver [seção 11](#11-próximos-passos-técnicos))
- `encerrar()` não bloqueia mais esperando 100% dos itens contados — item não contado recebe `quantidade_fisica = quantidade_sistema` automaticamente
- Laudo em PDF: `GET /api/inventarios/<id>/laudo/`, gerado com `reportlab`, logo da Engemil + tabela completa de itens, paginação automática

**Frontend**
- React 19 + TypeScript + Vite + React Router 7 + TanStack Query + Axios + Ant Design 6 (ver nota de versão em [seção 3](#stack))
- Autenticação JWT completa (login por CPF com máscara, logout, rota protegida, bloqueio de primeiro acesso)
- Layout principal (sidebar + header) com identidade visual do cliente (ver [seção 9](#identidade-visual))
- 6 telas de listagem com dado real (Materiais, Solicitações, Entradas, Devoluções, Inventário, Movimentações), todas com busca/filtro
- Formulários de criação com `Form.List` de itens dinâmicos (Solicitação, Entrada)
- Actions de negócio completas: Confirmar Saída, Cancelar e **Editar** Solicitação (cabeçalho + itens, novo); Confirmar Entrada (com modal de conferência); Informar, Aprovar e Rejeitar Devolução, com tela de detalhes mostrando o motivo de rejeição em destaque (novo); Iniciar, contar e Encerrar Inventário (encerrar com item não contado restrito a Engenheiro/Administrador no front, espelhando o backend); download de laudo em PDF
- Cadastros completos (listar/criar/editar): Unidade de Medida, Fornecedor, Posto, Demanda, Perfil, Usuário (+ resetar senha)
- Dashboard inicial com indicadores resumidos + **saldo total em estoque** (novo: saldo do estoque atual + saldo das solicitações atendidas, `GET /api/dashboard/resumo/`)
- Tela de contagem do Inventário oculta a coluna "Qtd. Sistema" para o perfil Almoxarifado (quem faz a contagem física), para não influenciar a contagem manual — Engenheiro/Administrador continuam vendo
- Componente `NumeroTabela` (fonte monoespaçada) aplicado nas colunas numéricas
- Tratamento de erro robusto (`extrairMensagemErro`, com guard contra resposta HTML não-JSON)

**Deploy — Ambiente de Demonstração**
- Backend hospedado no Render (`https://engemil.onrender.com`), com PostgreSQL gratuito
- Frontend hospedado no Render como Static Site
- `build.sh` automatiza `pip install`, `collectstatic`, `migrate`, `seed_inicial`, `seed_teste_perfis`, `importar_materiais`, `seed_demo` a cada deploy
- WhiteNoise servindo arquivos estáticos em produção; Gunicorn como servidor WSGI
- Versão do Python fixada via `.python-version` (padrão correto do Render)
- JWT com validade estendida (8h access / 7 dias refresh) para não expirar durante demonstrações

### 🆕 Novidades e 🔥 Removido (17-18/08/2026 e 24/08/2026)

- **Fluxo de separação da Solicitação (novo, 24/08)**: dois passos manuais novos antes da saída física. (1) `SolicitacaoService.separar()` — Almoxarifado informa, item a item, quanto já separou fisicamente (`ItemSolicitacao.quantidade_separada`, acumula, aceita parcial); revalida disponibilidade a cada chamada; item vira `SEPARADO` só quando `quantidade_separada >= quantidade_solicitada`; NÃO debita `Material.estoque_real`. (2) Quando todo item não cancelado está `SEPARADO`, `POST /solicitacoes/<id>/disponivel-para-retirada/` muda `Solicitacao.status` pra `DISPONIVEL_PARA_RETIRADA` — nada disso é automático. `confirmar-saida` (inalterado por dentro) passou a operar só sobre itens `SEPARADO`, e seu botão no frontend só aparece em `DISPONIVEL_PARA_RETIRADA`/`PARCIALMENTE_ATENDIDA`. Criação de Solicitação também mudou: item com `quantidade_solicitada > Material.estoque_real` é bloqueado na hora (`SolicitacaoCreateSerializer`) — não nasce mais `INDISPONIVEL` por erro de cadastro, só por corrida real de estoque depois. Ver [seção 6](#6-regras-de-negócio-críticas) e [seção 8](#8-referência-de-api)
- **Saída via estoque do Senado (novo, 24/08)**: `ItemSolicitacao.quantidade_saida_senado` — quanto da saída confirmada veio do estoque do Senado, não do estoque controlado pela aplicação. `quantidade_atendida` continua refletindo o total entregue; só `quantidade_atendida - quantidade_saida_senado` é de fato debitado do `Material.estoque_real` (via `Movimentacao`, quantidade menor, sem tabela nova). Payload opcional `itens_senado` em `POST /confirmar-saida/` — ver [seção 6](#6-regras-de-negócio-críticas) e [seção 8](#8-referência-de-api)
- **Responsável pela retirada (novo, 24/08)**: `Movimentacao.responsavel_retirada` (nullable no model, obrigatório no fluxo) — nome de quem retira fisicamente o material, informado em `confirmar-saida`, gravado em cada `Movimentacao` de `SAIDA` gerada naquela chamada (não em `Solicitacao` — de propósito, pra não perder o nome de confirmações parciais anteriores quando a retirada é dividida entre pessoas diferentes). Exposto em `MovimentacaoSerializer` e na tela de Movimentações
- **Almoxarifado cadastra Unidade de Medida e Fornecedor (novo, 24/08)**: `UnidadeMedidaViewSet`/`FornecedorViewSet` tinham `funcoes_somente_leitura = {ALMOXARIFADO}` residual — travava em leitura mesmo já estando em `funcoes_permitidas`. Removido dos dois (bug, não decisão — Posto/Demanda/ReferenciaTecnica/Perfil/Usuário continuam como estavam, intocados). Frontend: menu "Cadastros" deixou de ser um bloco único (`acessoPorFuncao.cadastros`) — cada item agora tem acesso individual (`unidadesMedida`/`fornecedores`/`postos`/`perfis`/`usuarios`), então o Almoxarifado só vê os 2 itens liberados
- **Edição de Solicitação (novo)**: `PATCH`/`PUT /api/solicitacoes/<id>/`, cabeçalho + itens, só em status editáveis — ver [seção 6](#6-regras-de-negócio-críticas)
- **Reabertura de Solicitação — implementada e removida**: chegou a existir, foi revertida por deixar itens e cabeçalho dessincronizados; a Edição acima cobre a necessidade. Sem status `REABERTA`, sem `reaberta_em`
- **Dashboard — saldo total em estoque (novo)**: `GET /api/dashboard/resumo/`
- **Demanda virou opcional** na Solicitação (contexto tirado de uso por enquanto)
- **`responsavel_conferencia_nome` exposto** no serializer de Devolução
- **Frontend**: tela de detalhes da Devolução com motivo de rejeição em destaque; coluna "Qtd. Sistema" do Inventário oculta para o Almoxarifado (evita influenciar a contagem manual); paleta de cores do cliente commitada (pendência anterior resolvida)

### 🔧 Corrigido (bugs reais)

| Bug | Causa | Correção |
|---|---|---|
| Encerrar Inventário podia quebrar com `SaldoInsuficienteError` cru | `encerrar()` calculava o ajuste contra o retrato do início do inventário sem revalidar o saldo atual do material | Item cujo ajuste não coube mais fica marcado como pendente na `observacao` (visível no laudo), resto do encerramento segue normal |
| Aprovar devolução podia estourar `500` cru | `aprovar()` não revalidava saldo disponível — uma segunda devolução do mesmo item podia violar constraint do banco | `SaldoDevolucaoInsuficienteError` validado também em `aprovar()`, não só na criação |
| Duas devoluções pendentes do mesmo item ao mesmo tempo | Nenhuma trava de concorrência | `DevolucaoJaAbertaError` — só uma devolução em aberto por item por vez |
| Erro genérico `"<"` no frontend em respostas não-JSON | Resposta HTML de erro sendo iterada como objeto | Guard `typeof dados !== 'object'` em `extrairMensagemErro` |
| Encarregado via botão "Confirmar Saída" mesmo sem permissão | Backend já bloqueava (`403`), frontend não escondia o botão | Botão só renderiza para o grupo de perfis correto |
| `loading` acendia em todas as linhas da tabela ao salvar uma contagem | `mutation.isPending` sozinho não distingue qual item está sendo salvo | Comparação por ID do item em processamento |
| Código de material longo atropelava coluna no PDF do laudo | Texto simples não quebra linha em `Table` do reportlab | Texto envolvido em `Paragraph` |

### 📌 Estado do git (18/08/2026)

- **Backend**: `develop` sincronizado com `origin/develop` (nada pendente de push). 10 commits em `develop` ainda não mesclados em `main`.
- **Frontend**: `develop` sincronizado com `origin/develop` (nada pendente de push, nada não commitado). 26 commits em `develop` ainda não mesclados em `main`. A paleta de cores do cliente (ver [seção 9](#identidade-visual)) **já está commitada** — pendência anterior resolvida.
- O ambiente de demonstração no Render normalmente reflete `main`; portanto o deploy público pode estar **atrás** do que está em `develop` até o próximo merge — checar antes de apresentar ao cliente.

---

## 3. Arquitetura

### Stack

| Camada | Tecnologia | Versão confirmada |
|---|---|---|
| Backend | Django | 5.0.6 |
| | Django REST Framework | 3.15.1 |
| | djangorestframework-simplejwt | 5.3.1 |
| | django-filter | 24.2 |
| | PostgreSQL | 16 |
| | Python (via pyenv) | 3.12.7 — **nunca 3.14** |
| | reportlab (laudo PDF) | 5.0.0 |
| | Servidor WSGI | Gunicorn 22.0.0 + WhiteNoise 6.7.0 |
| Frontend | React | **19.2.8** |
| | TypeScript | ~6.0.2 |
| | Vite | 8.2.1 |
| | React Router | **7.18.2** |
| | Ant Design | **6.6.0** |
| | TanStack Query (React Query) | 5.101.4 |
| | Axios | 1.19.0 |
| Deploy | Render.com | Web Service (backend) + Static Site (frontend), sem Docker |

> **Nota de correção**: a documentação técnica interna do frontend registrava React 18 / Ant Design 5 como stack — desatualizado. O `package-lock.json` confirma React 19.2.8, Ant Design 6.6.0 e React Router 7.18.2 de fato instalados e em uso.

### Fluxo de dados (ponta a ponta)

```mermaid
flowchart LR
    FE["Frontend (React/Axios)\nheader Authorization: Bearer JWT"] --> URLS["api/urls.py\n(DefaultRouter)"]
    URLS --> VIEWS["api/views/*.py\nViewSets DRF — só HTTP"]
    VIEWS --> PERM["api/permissions.py\nPerfilPermission"]
    VIEWS --> SER["api/serializers/*.py\nvalidação de forma"]
    SER --> SVC["app/domain/services.py\nregra de negócio"]
    SVC --> MOV["core/domain/services.py\nMovimentacaoService\n(único ponto que cria Movimentacao)"]
    MOV --> ORM["app/models.py\nDjango ORM"]
    ORM --> DB[("PostgreSQL")]
```

**Regra inegociável**: nenhuma alteração de saldo de estoque acontece fora de `MovimentacaoService`. Todo app de domínio delega a ele.

### Árvore do projeto — backend

```
engemil/
├── manage.py
├── requirements.txt
├── build.sh                          # roda no deploy do Render
├── .python-version                   # "3.12.7"
├── data/Lista_de_materiais_Engemil.xlsx
├── config/
│   ├── settings/{base,development,production}.py
│   ├── urls.py / wsgi.py / asgi.py
├── core/                              # bounded context central — nunca importa dos outros apps
│   ├── models.py                     # Perfil, Posto, Usuario, UnidadeMedida, ReferenciaTecnica,
│   │                                   Fornecedor, Demanda, Material, Movimentacao
│   ├── validators.py                 # validar_cpf, validar_telefone, validar_quantidade_por_unidade
│   ├── domain/
│   │   ├── value_objects.py          # OrigemMovimentacao
│   │   └── services.py               # MovimentacaoService, SaldoEstoqueService
│   ├── management/commands/          # seed_inicial, seed_teste_perfis, importar_materiais, seed_demo
│   └── admin.py                      # só core registrado no Django Admin
├── solicitacoes/    (models.py + domain/services.py — SolicitacaoService)
├── entradas/        (models.py + domain/services.py — EntradaService)
├── devolucoes/      (models.py + domain/services.py — DevolucaoService)
├── inventario/      (models.py + domain/services.py + domain/relatorio.py — InventarioService, PDF)
└── api/                               # única camada HTTP
    ├── permissions.py
    ├── urls.py
    ├── serializers/{core,solicitacoes,entradas,devolucoes,inventario}.py
    └── views/{core,solicitacoes,entradas,devolucoes,inventario}.py
```

### Árvore do projeto — frontend

```
engemil-frontend/
├── index.html
├── src/
│   ├── main.tsx / App.tsx / routes.tsx / theme.ts
│   ├── types/            # singular — interfaces TS espelhando serializers DRF
│   ├── api/               # plural — funções axios por domínio
│   ├── hooks/             # useUsuarioAtual, useDebouncedValue
│   ├── access/            # acessoPorFuncao.ts — matriz área → perfis, espelha o backend
│   ├── components/        # ProtectedRoute, RequireSenhaAtualizada, RequireFuncao, NumeroTabela, SenhaGeradaModal
│   ├── layouts/           # MainLayout
│   ├── utils/             # formatarData, unidadesContaveis, formatarMoeda, statusLabels, extrairErro
│   └── pages/
│       ├── Login.tsx, DashboardPage.tsx, TrocarSenhaObrigatoria.tsx
│       ├── materiais/, solicitacoes/, entradas/, devolucoes/, inventario/, movimentacoes/
│       └── cadastros/{unidadesMedida,fornecedores,postos,demandas,perfis,usuarios}/
```

### Padrões e regras de arquitetura (backend — não reabrir sem necessidade)

1. Domínio vive em `<app>/domain/services.py`, separado de `models.py` — separação pragmática, não é Clean Architecture total
2. `core` nunca importa dos outros apps de domínio; eles importam de `core`
3. FK entre apps via string (`'app.Model'`) — evita import circular em Python
4. Toda regra de negócio que existe como `CheckConstraint` no banco precisa de `validate()` espelhado no serializer correspondente — sem isso, violação de constraint vira `500` cru em vez de `400` com mensagem
5. `UniqueConstraint` composta (multi-campo) não é validada automaticamente pelo DRF — precisa de `validate_itens()` customizado
6. Padrão de serializer: um para leitura, outro para criação (`XSerializer`/`XCreateSerializer`), escolhido via `get_serializer_class()`
7. Ações de mutação usam DRF `@action`
8. Senhas: nunca aceitar `password` bruto — sempre via `Usuario.objects.create_user()`/`set_password()`
9. Escopo por perfil em `get_queryset()` (o quê vê) é distinto de `funcoes_permitidas` (se acessa)
10. `funcoes_somente_leitura` libera leitura de recursos de apoio sem liberar a gestão deles
11. Permissão de objeto individual (`ApenasProprioSolicitante` etc.) sempre em conjunto com o filtro equivalente em `get_queryset()`
12. Saldo materializado: valor lido com frequência mas caro de calcular é materializado num campo mantido pelo único service autorizado a escrevê-lo, na mesma transação do evento de origem (`Material.estoque_real`)

---

## 4. Modelo de dados

### `core` — entidades de apoio e transversais

| Entidade | Campos-chave | Observações |
|---|---|---|
| `Perfil` | `nome`, `funcao` (única) | `funcao` é a chave de negócio usada nas regras de permissão |
| `Posto` | `codigo` (único), `nome`, `responsavel` (FK `Usuario`, nullable) | `responsavel` (quem responde pelo posto) é **distinto** de `Usuario.posto` (lotação) |
| `Usuario` | `cpf` (único, login), `nome`, `sobrenome`, `email`, `senha_temporaria`, `situacao`, `perfil` (FK), `posto` (FK, nullable) | `AUTH_USER_MODEL`. `is_active` é `@property` derivada de `situacao`, não coluna própria |
| `UnidadeMedida` | `sigla` (única), `descricao` | Contáveis: `un`, `pct`, `cx`; contínuas: `m`, `m2`, `m3`, `cm2`, `cm3`, `kg` |
| `ReferenciaTecnica` | `codigo` (única), `nome` | |
| `Fornecedor` | `nome`, `cnpj` (único), `telefone`, `email` | Validação de CNPJ ainda **não implementada** (só formato) |
| `Demanda` | `numero` (único), `descricao`, `origem`, `prazo`, `situacao` | |
| `Material` | `codigo` (único), `descricao` (único campo que nomeia o item), `unidade` (FK), `estoque_minimo` (opcional), `valor_unitario` (preço cadastral, opcional), `estoque_real` (materializado, somente leitura), `situacao` | `estoque_real` é mantido **só** por `MovimentacaoService`. Falta `categoria`/`localizacao` (pendência de negócio) |
| `Movimentacao` | `material` (FK), 4 FKs de origem (`solicitacao`/`entrada`/`devolucao`/`item_inventario`, todas nullable, **exatamente 1 preenchida**), `usuario`, `responsavel_retirada` (novo, 24/08), `tipo`, `quantidade_anterior/posterior` (unidades físicas), `saldo_anterior/posterior` (R$) | Tabela-fato de auditoria, append-only. Regra de origem única validada em Python (`OrigemMovimentacao`) **e** `CheckConstraint` no banco. `responsavel_retirada` (nullable) é o nome de quem retirou fisicamente o material — não é um `Usuario` do sistema (diferente de `usuario`, que é sempre o Almoxarifado que confirmou); só preenchido em `SAIDA` vinda de `confirmar_saida`, obrigatório nesse fluxo |

### `solicitacoes`

| Entidade | Campos-chave | Observações |
|---|---|---|
| `Solicitacao` | `numero` (único), `status` (6 estados), `data_solicitacao`, `data_prevista` (opcional, auto-preenchida), `demanda` (FK, **opcional**), `posto`/`solicitante` (FK) | Status: `ABERTA`, `EM_ANDAMENTO`, `DISPONIVEL_PARA_RETIRADA` (novo, 24/08 — todo item não cancelado já `SEPARADO`), `PARCIALMENTE_ATENDIDA`, `ATENDIDA`, `CANCELADA` — não existe status `REABERTA`. A feature de reabrir foi implementada e depois **removida** (campo `reaberta_em` também removido) — ver seção 6 |
| `ItemSolicitacao` | `solicitacao`/`material` (FK, único juntos), `quantidade_solicitada`, `quantidade_separada`, `quantidade_atendida`, `quantidade_devolvida`, `quantidade_saida_senado`, `status`, `observacao` (obrigatória na criação via API) | Status: `PENDENTE`, `SEPARADO` (novo, 24/08), `DISPONIVEL`, `INDISPONIVEL`, `ATENDIDO`, `CANCELADO`. Quantidades separada/atendida/devolvida/saída-senado são campos derivados, nunca fonte de verdade. `quantidade_separada` acumula via `SolicitacaoService.separar()` (etapa manual, não debita estoque); item só vira `SEPARADO` quando `quantidade_separada >= quantidade_solicitada`. `quantidade_saida_senado` (sempre `<= quantidade_atendida`) é a fração da saída que veio do estoque do Senado — só `quantidade_atendida - quantidade_saida_senado` é debitado do `Material.estoque_real` |

### `entradas`

| Entidade | Campos-chave | Observações |
|---|---|---|
| `Entrada` | `fornecedor` (FK, nullable), `responsavel` (FK), `nota_fiscal`, `data_entrada`, `confirmada_em` (nullable) | `confirmada_em` protege contra dupla confirmação |
| `ItemEntrada` | `entrada`/`material` (FK), `quantidade`, `valor_unitario`, `valor_total` | `valor_total` sempre calculado no `save()`, nunca aceito como input |

### `devolucoes`

| Entidade | Campos-chave | Observações |
|---|---|---|
| `Devolucao` | `item_solicitacao` (FK), `responsavel_conferencia` (FK), `quantidade`, `condicao` (bool), `decisao` (bool), `data_inicial`, `data_final` (nullable) | Estado de 3 posições sem enum: `data_final IS NULL` = pendente; `decisao` só vale depois de `data_final` preenchido. `DevolucaoSerializer` expõe `responsavel_conferencia_nome` (read-only) |

### `inventario`

| Entidade | Campos-chave | Observações |
|---|---|---|
| `Inventario` | `data_inicio`, `data_fim`, `encerrado_em`/`encerrado_por` (nullable), `situacao`, `observacao` | Situação: `EM_ANDAMENTO`, `ENCERRADO`, `CANCELADO`. `CheckConstraint` garante que `encerrado_em`/`encerrado_por` só existem junto de `ENCERRADO` |
| `ParticipanteInventario` | `inventario`/`usuario` (único juntos), `funcao` | |
| `ItemInventario` | `inventario`/`material` (único juntos), `saldo_sistema` (R$), `quantidade_sistema`, `quantidade_fisica` (nullable = não contado), `divergencia`, `ajuste`, `observacao` | Snapshot do saldo/quantidade no momento do início do inventário — não recalcula depois |

### Diagrama de relacionamento (visão simplificada)

```mermaid
erDiagram
    Usuario }o--|| Perfil : "tem"
    Usuario }o--o| Posto : "lotado em"
    Posto |o--o| Usuario : "responsável"
    Material }o--|| UnidadeMedida : "medido em"
    Material }o--o| ReferenciaTecnica : "referencia"

    Solicitacao }o--|| Demanda : "atende"
    Solicitacao }o--|| Posto : "destino"
    Solicitacao }o--|| Usuario : "solicitante"
    Solicitacao ||--o{ ItemSolicitacao : "contém"
    ItemSolicitacao }o--|| Material : "referencia"
    ItemSolicitacao ||--o{ Devolucao : "pode gerar"

    Entrada }o--o| Fornecedor : "de"
    Entrada ||--o{ ItemEntrada : "contém"
    ItemEntrada }o--|| Material : "referencia"

    Inventario ||--o{ ItemInventario : "contém"
    ItemInventario }o--|| Material : "referencia"

    Movimentacao }o--|| Material : "afeta saldo de"
    Movimentacao }o--o| Solicitacao : "origem"
    Movimentacao }o--o| Entrada : "origem"
    Movimentacao }o--o| Devolucao : "origem"
    Movimentacao }o--o| ItemInventario : "origem"
```

---

## 5. Perfis e permissões

### Perfis (`core.Perfil.funcao`)

6 perfis fixos: `ENCARREGADO` (PER-01), `ALMOXARIFADO` (PER-02), `COMPRAS` (PER-03), `ENGENHEIRO` (PER-04), `ADMINISTRADOR` (PER-05), `CONSULTA` (PER-06).

- **`ADMINISTRADOR` e `ENGENHEIRO` têm acesso irrestrito a tudo** — confirmado pelo cliente (`Funcao.SEMPRE_PERMITIDOS`)
- **Só `ADMINISTRADOR`/`ENGENHEIRO` podem criar/gerenciar usuários**
- **Login é por CPF**, nunca e-mail nem `nome.sobrenome` (descartado por risco de colisão entre homônimos)
- **Todo usuário novo recebe senha aleatória gerada pelo sistema**, mostrada uma única vez, nunca recuperável depois
- **Usuário com senha temporária é bloqueado de usar o sistema até trocar a senha**
- `COMPRAS` e `CONSULTA` ficam **sem nenhum acesso** até terem definição própria com o cliente — pendência de negócio

### Matriz de acesso — fechada e implementada

| Área | Admin/Engenheiro | Almoxarifado | Encarregado |
|---|---|---|---|
| Materiais | ver+criar+editar | ver+criar+editar (todos) | **ver (só leitura)** |
| Solicitações | ver+criar+editar (todas) | ver+criar+editar (todas) | ver+criar+editar — **só as que ele criou** |
| Entradas | ver+criar+editar | ver+criar+editar (todas) | ❌ sem acesso |
| Devoluções | ver+criar+editar (todas) | ver+criar+editar (todas) | ver+criar+editar — **só ligadas às solicitações dele** |
| Inventário | ver+criar+editar | ver+criar+editar (todas) | ❌ sem acesso |
| Movimentações | ver (todas, só leitura) | ver (todas, só leitura) | ver (só leitura) — **só SAÍDA/DEVOLUÇÃO originadas dele** |
| Cadastros — UnidadeMedida/Fornecedor (24/08) | ver+criar+editar | **ver+criar+editar** (mesma aba "Cadastros" do menu, só esses 2 itens aparecem) | ❌ sem acesso à aba |
| Cadastros — Posto/Demanda/ReferenciaTecnica/Perfil/Usuário | ver+criar+editar | ❌ sem acesso à aba; **leitura liberada** nos recursos que suas telas precisam (Posto, Demanda) | ❌ sem acesso à aba; leitura liberada só em Demanda+Posto |

Implementado em `api/permissions.py` e espelhado no frontend em `src/access/acessoPorFuncao.ts` (mesma fonte de verdade para menu e bloqueio de rota).

**Escopo do Encarregado é individual** (`solicitante = request.user`), não por posto — cada usuário pertence a um único posto e é responsável só por ele.

---

## 6. Regras de negócio críticas

| Regra | Descrição | Implementação |
|---|---|---|
| **RN-002** | Solicitação precisa de pelo menos 1 item | `SolicitacaoCreateSerializer.validate_itens()` |
| **RN-006/RN-007** | `Movimentacao` é append-only — nunca editada/excluída, erro se corrige com movimentação compensatória | Convenção de código, reforçada por FK `on_delete=PROTECT` |
| **RN-010** | Material danificado nunca retorna ao estoque | `DevolucaoService.aprovar()` levanta `MaterialDanificadoNaoRetornaAoEstoqueError` se `condicao=False`; único caminho é `rejeitar()` |
| **RN-011** | Não pode sair mais que o saldo disponível | `MovimentacaoService` levanta `SaldoInsuficienteError`; checagem em unidades físicas, não em R$ |
| Atendimento parcial | Item sem estoque fica `INDISPONIVEL` sem bloquear os demais itens da solicitação | `confirmar_saida()` processa item a item, atômico só para o lote elegível |
| Separação antes da saída | `confirmar_saida()` só pega itens já `SEPARADO` — `PENDENTE` nunca entra, mesmo com estoque disponível | Filtro `status=SEPARADO` em `confirmar_saida()` |
| Separação parcial e revalidação | `separar()` aceita quantidade menor que a solicitada (acumula); revalida disponibilidade a cada chamada — pode ter mudado desde a criação | `SeparacaoInvalidaError` (`400`, quantidade/estado inválido), `DisponibilidadeInsuficienteError` (`409`, sem estoque) |
| Disponível para retirada exige tudo separado | Só marca `DISPONIVEL_PARA_RETIRADA` se todo item não cancelado estiver `SEPARADO` | `DisponivelParaRetiradaInvalidaError` (`409`) |
| Item não nasce sem estoque | Criação bloqueia item com `quantidade_solicitada > Material.estoque_real` (cobre estoque zerado também) | `SolicitacaoCreateSerializer.validate_itens` (`400`) |
| Confirmação de Entrada protegida | Confirmar duas vezes não duplica movimentação | `confirmada_em` (nullable) + `EntradaJaConfirmadaError` (`409`) |
| Quantidade inteira por unidade contável | `un`/`pct`/`cx` só aceitam inteiro; `m`/`m2`/`m3`/`cm2`/`cm3`/`kg` aceitam fração | `validar_quantidade_por_unidade`, aplicado em todo serializer que recebe quantidade ligada a material. **Gap conhecido**: Django Admin não passa pelos serializers, então não valida isso |
| Custeio de saída — placeholder | `MovimentacaoService._custo_unitario_estimado()` usa "custo da última entrada" — **não é** CMP nem FIFO, decisão pendente do cliente | Isolado num único método para facilitar troca futura. Não confundir com `Material.valor_unitario` (preço cadastral, para exibição, sem relação com custeio) |
| Só uma devolução pendente por item | Nova devolução recusada se já existe uma com `data_final IS NULL` | `DevolucaoJaAbertaError` (`400`) |
| Quantidade devolvida ≤ disponível | `disponível = quantidade_atendida - quantidade_devolvida`, recalculado no submit, validado em **duas** pontas (`informar()` e `aprovar()`) | `SaldoDevolucaoInsuficienteError` (`409`) |
| Edição de Solicitação | Só `ABERTA`/`EM_ANDAMENTO`/`PARCIALMENTE_ATENDIDA`; item com `quantidade_atendida > 0` não troca material, não reduz abaixo do atendido, não é removido | `SolicitacaoEditSerializer` (`PATCH`/`PUT /solicitacoes/<id>/`) |
| ~~Reabertura de Solicitação~~ | **Removida** (implementada e depois revertida) — deixava itens `ATENDIDO` dessincronizados do cabeçalho voltado a `ABERTA`; a Edição de Solicitação acima cobre a necessidade real | — |
| Ajuste de Inventário não coube no saldo atual | `quantidade_sistema` é retrato do início do inventário; se o saldo real mudou, o ajuste calculado pode violar `SaldoInsuficienteError` na hora de encerrar | Item fica com ajuste pendente na `observacao` (não derruba o encerramento); resposta ganha `aviso` |
| Encerrar Inventário com item não contado | Só Engenheiro/Administrador pode substituir a contagem física pela quantidade do sistema; Almoxarifado precisa de 100% contado manualmente | `403` na view se Almoxarifado tentar com item pendente |
| Saída via estoque do Senado | `quantidade_saida_senado` (opcional, por item, em `confirmar-saida`) nunca pode exceder a quantidade pendente do item nesta chamada, nem ser informada para item fora do lote elegível desta confirmação. A fração Senado não é debitada do `Material.estoque_real` — só `quantidade_pendente - quantidade_saida_senado` sai de fato (inclusive na checagem de disponibilidade); pode chegar a `0` (saída 100% coberta pelo Senado) | `QuantidadeSaidaSenadoInvalidaError` (`400`) |
| Responsável pela retirada obrigatório | `confirmar-saida` exige `responsavel_retirada` (nome de quem retira fisicamente, não precisa ser `Usuario` do sistema) — grava em `Movimentacao.responsavel_retirada` pra cada item confirmado nesta chamada | `ResponsavelRetiradaObrigatorioError` (`400`) |

---

## 7. Fluxos de trabalho

### Visão geral — tudo converge para `Movimentacao`

```mermaid
flowchart LR
    Entrada["Entrada confirmada"] -->|tipo=ENTRADA| Mov[("Movimentacao\ntabela-fato, append-only")]
    Saida["Solicitação — saída confirmada"] -->|tipo=SAIDA| Mov
    Devolucao["Devolução aprovada"] -->|tipo=DEVOLUCAO| Mov
    Inventario["Inventário encerrado\ncom divergência"] -->|tipo=AJUSTE_INVENTARIO| Mov
    Mov --> Estoque["Material.estoque_real\nmaterializado"]
```

### Entrada de material

```mermaid
flowchart TD
    A["Almoxarifado/Engenheiro\nPOST /api/entradas/"] --> B["Entrada criada\nconfirmada_em = null"]
    B --> C["Modal de detalhes\nantes de confirmar"]
    C --> D["POST /entradas/id/confirmar/"]
    D --> E{confirmada_em já preenchido?}
    E -->|sim| F["409 EntradaJaConfirmadaError"]
    E -->|não| G["EntradaService.confirmar()"]
    G --> H["MovimentacaoService.registrar_entrada()\n1 Movimentacao ENTRADA por item"]
    H --> I["Material.estoque_real += quantidade"]
```

### Solicitação → Saída (criar, confirmar, cancelar, editar)

```mermaid
flowchart TD
    A["Encarregado\nPOST /api/solicitacoes/"] --> B{"pelo menos 1 item?"}
    B -->|não| B1[400]
    B -->|sim| C["Solicitacao — status ABERTA"]
    C --> D["Almoxarifado/Admin/Engenheiro\nPOST /confirmar-saida/"]
    D --> E["por item pendente,\nverifica disponibilidade"]
    E -->|disponível| F["Movimentacao SAIDA\nitem → ATENDIDO"]
    E -->|indisponível| G["item → INDISPONIVEL"]
    F --> H{recalcula status}
    G --> H
    H -->|todos ATENDIDO| H1[ATENDIDA]
    H -->|parte ATENDIDO| H2[PARCIALMENTE_ATENDIDA]
    H -->|nenhum ainda| H3[EM_ANDAMENTO]
    C --> K["Dono ou Almoxarifado\nPOST /cancelar/"]
    K --> K1["Solicitacao → CANCELADA"]
    H2 --> ED["PATCH/PUT /solicitacoes/id/\n(NOVO — não em ATENDIDA/CANCELADA)"]
    H3 --> ED
    ED -->|"item já com saída"| ED1["não troca material,\nnão reduz, não remove"]
    ED --> ED2["reconciliar_status_apos_edicao()\n— não força avanço de ciclo sozinha"]
```

> **Reabertura removida** (18/08/2026): existiu `POST /reabrir/` + `Solicitacao.reaberta_em`, mas foi revertida por deixar itens `ATENDIDO` dessincronizados do cabeçalho — a Edição de Solicitação acima resolve a necessidade sem essa inconsistência.

### Devolução

```mermaid
flowchart TD
    A["POST /api/devolucoes/"] --> B{devolução pendente já existe neste item?}
    B -->|sim| B1["400 DevolucaoJaAbertaError"]
    B -->|não| C{quantidade ≤ disponível?}
    C -->|não| C1["409 SaldoDevolucaoInsuficienteError"]
    C -->|sim| D["Devolucao criada — pendente"]
    D --> F["POST /aprovar/"]
    D --> G["POST /rejeitar/"]
    F --> H{condicao == False?}
    H -->|sim| H1["409 RN-010 — bloqueado"]
    H -->|não| I{saldo ainda suficiente?}
    I -->|não| I1["409 SaldoDevolucaoInsuficienteError"]
    I -->|sim| J["Movimentacao DEVOLUCAO\nestoque_real += quantidade"]
    G --> K["nunca gera Movimentacao"]
```

### Inventário (iniciar, contar, encerrar, laudo)

```mermaid
flowchart TD
    A["Almoxarifado\nPOST /api/inventarios/"] --> B["inclui automaticamente\ntodos os materiais ATIVO\n(⚠️ capado em 10 para demo)"]
    B --> C["1 ItemInventario por material\nsnapshot do saldo no momento"]
    C --> D["Contagem física item a item"]
    D --> F["POST /encerrar/"]
    F --> P{"item não contado\ne quem encerra não é\nEngenheiro/Admin?"}
    P -->|sim| P1["403"]
    P -->|não| G{item foi contado?}
    G -->|não| G1["quantidade_fisica = quantidade_sistema\ndivergência 0"]
    G -->|sim| G2["usa valor contado"]
    G1 --> H{divergência != 0?}
    G2 --> H
    H -->|sim| H1{"ajuste cabe no\nsaldo atual?"}
    H -->|não| H2["sem ajuste"]
    H1 -->|sim| H1A["Movimentacao AJUSTE_INVENTARIO"]
    H1 -->|"não — SaldoInsuficienteError"| H1B["ajuste pendente\nna observação do item"]
    H1A --> I["situacao → ENCERRADO"]
    H1B --> I
    H2 --> I
    I -->|"algum item pendente"| IA["resposta ganha 'aviso'"]
    C --> L["GET /laudo/\nqualquer situação"]
    I --> L
    L --> M["PDF via reportlab"]
```

### Criação de usuário + primeiro acesso / reset de senha

```mermaid
flowchart TD
    A["Admin/Engenheiro\nPOST /api/usuarios/ (sem senha)"] --> B["senha aleatória gerada\nsenha_temporaria = True"]
    B --> C["resposta devolve senha_gerada\nUMA ÚNICA VEZ"]
    C --> D["login com CPF + senha temporária"]
    D --> E["GET /usuarios/me/ detecta\nsenha_temporaria=True"]
    E --> F["navegação bloqueada"]
    F --> G["POST /usuarios/trocar-senha/"]
    G --> H["senha_temporaria = False\nsistema liberado"]
    R["POST /usuarios/id/resetar-senha/"] --> B
```

---

## 8. Referência de API

Base: `/api/`. Autenticação via header `Authorization: Bearer <access_token>`.

### Autenticação

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/auth/token/` | Login — recebe CPF+senha, devolve `access`/`refresh` |
| POST | `/auth/token/refresh/` | Renova o `access token` a partir do `refresh` |

### CRUD padrão (via `DefaultRouter`)

Todos suportam `GET` (list/retrieve), `POST`, `PATCH`, `DELETE` conforme a permissão do perfil, paginação (`{count, next, previous, results}`) e, na maioria, `?search=` e filtros por campo:

`materiais`, `unidades-medida`, `referencias-tecnicas`, `fornecedores`, `demandas`, `postos`, `usuarios`, `perfis`, `movimentacoes` (**só leitura**), `solicitacoes`, `entradas`, `devolucoes`, `inventarios`, `itens-inventario`

### Actions de negócio (`@action`)

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/usuarios/me/` | Dados do usuário autenticado |
| POST | `/usuarios/trocar-senha/` | Troca a própria senha (`senha_atual` + `nova_senha`) |
| POST | `/usuarios/<id>/resetar-senha/` | Admin/Engenheiro gera nova senha temporária para outro usuário |
| POST | `/entradas/<id>/confirmar/` | Confirma entrada, gera `Movimentacao` |
| GET | `/solicitacoes/<id>/disponibilidade/` | Verifica disponibilidade de estoque dos itens |
| POST | `/itens-solicitacao/<id>/separar/` | (novo, 24/08) Registra separação física do item, `{"quantidade": "3.000"}` — acumula em `quantidade_separada`, aceita parcial, revalida estoque; `400` `SeparacaoInvalidaError` / `409` `DisponibilidadeInsuficienteError` |
| POST | `/solicitacoes/<id>/disponivel-para-retirada/` | (novo, 24/08) Marca a solicitação como `DISPONIVEL_PARA_RETIRADA` — exige todo item não cancelado já `SEPARADO`; `409` `DisponivelParaRetiradaInvalidaError` |
| POST | `/solicitacoes/<id>/confirmar-saida/` | Confirma saída (atendimento total ou parcial) — só sobre itens já `SEPARADO`. Body: `responsavel_retirada` (obrigatório, string — nome de quem retira, grava em `Movimentacao.responsavel_retirada`; `400` se ausente/em branco) + `itens_senado` opcional `[{"item": "<uuid>", "quantidade": "3.000"}]` — informa quanto da saída de cada item veio do estoque do Senado; essa fração acumula em `quantidade_saida_senado` e NÃO é debitada de `Material.estoque_real` (`400` se quantidade > pendente do item ou item fora do lote desta chamada) |
| POST | `/solicitacoes/<id>/cancelar/` | Cancela solicitação (`ABERTA`/`EM_ANDAMENTO`/`PARCIALMENTE_ATENDIDA`/`DISPONIVEL_PARA_RETIRADA`) |
| PATCH/PUT | `/solicitacoes/<id>/` | Edita cabeçalho + itens (`ABERTA`/`EM_ANDAMENTO`/`PARCIALMENTE_ATENDIDA` só — `DISPONIVEL_PARA_RETIRADA` NÃO é editável) — via `update`/`partial_update` padrão do `ModelViewSet`, não é uma `@action` separada. Item reaberto (quantidade aumentada após `ATENDIDO`) volta pra `PENDENTE`, não mais `DISPONIVEL` — precisa passar de novo pela separação |
| POST | `/devolucoes/<id>/aprovar/` | Aprova devolução, gera `Movimentacao` (se em condição de uso) |
| POST | `/devolucoes/<id>/rejeitar/` | Rejeita devolução, nunca gera `Movimentacao` |
| POST | `/inventarios/<id>/participantes/` | Adiciona participante ao inventário |
| POST | `/inventarios/<id>/encerrar/` | Encerra inventário; item não contado só é auto-preenchido se quem encerra for Engenheiro/Administrador; item com ajuste que não coube no saldo atual fica pendente (`aviso` na resposta) |
| GET | `/inventarios/<id>/laudo/` | Gera e baixa laudo em PDF |
| POST | `/itens-inventario/<id>/contagem-fisica/` | Registra contagem física de um item |
| GET | `/dashboard/resumo/` | `saldo_estoque`, `saldo_solicitacoes_atendidas`, `saldo_total` (fora do `DefaultRouter`) |

> **`POST /solicitacoes/<id>/reabrir/` foi removido** (existiu, revertido em 18/08/2026) — não usar mais em integrações ou testes manuais.

### Filtros de busca implementados

| Endpoint | Parâmetros |
|---|---|
| `materiais` | `?search=` (código/descrição/fabricante), `?situacao=`, `?unidade=` |
| `solicitacoes` | `?search=` (número), `?status=`, `?posto=` (filtro `?demanda=` removido junto com a demanda virar opcional) |
| `entradas` | `?search=` (nota fiscal), `?fornecedor=`, `?confirmada=true\|false` |
| `devolucoes` | `?search=` (código/descrição do material), `?pendente=true\|false`, `?condicao=` |
| `inventarios` | `?situacao=` |
| `movimentacoes` | `?search=` (código/descrição do material) |
| `unidades-medida`, `referencias-tecnicas`, `fornecedores`, `postos`, `demandas` | `?search=`, `?situacao=` (onde aplicável) |
| `usuarios` | `?search=`, `?situacao=`, `?perfil=` |

---

## 9. Frontend — estrutura e padrões

### Rotas

```
/login                                          [público]
/  (ProtectedRoute)
  → RequireSenhaAtualizada
    → MainLayout
      → /                                        [Dashboard, sem guard extra]
      → RequireFuncao area="materiais"     → /materiais
      → RequireFuncao area="solicitacoes"  → /solicitacoes
      → RequireFuncao area="entradas"      → /entradas
      → RequireFuncao area="devolucoes"    → /devolucoes
      → RequireFuncao area="inventario"    → /inventario
      → RequireFuncao area="movimentacoes" → /movimentacoes
      → RequireFuncao area="cadastros"     → /cadastros/*
```

Quatro camadas de guarda: `ProtectedRoute` (está logado?) → `RequireSenhaAtualizada` (já trocou a senha obrigatória?) → `MainLayout` → `RequireFuncao` (o perfil tem acesso a essa área?). `ADMINISTRADOR`/`ENGENHEIRO` sempre passam.

### Padrões de código estabelecidos

- **Leitura**: `useQuery({ queryKey, queryFn })` + `data?.results` (a API sempre pagina)
- **Escrita (criar/editar unificado)**: modal recebe prop opcional `XParaEditar`, `mutationFn` escolhe `criarX`/`editarX` via ternário
- **Ação irreversível sem formulário**: `useMutation` disparada por botão/`Popconfirm`
- **Ações concorrentes na mesma tabela**: nunca usar `mutation.isPending` direto no `loading` de um botão de linha — comparar por ID do item em processamento (bug real já corrigido)
- **Quantidade por unidade**: `ehUnidadeContavel()`/`formatarQuantidade()` de `unidadesContaveis.ts`, espelhando a regra do backend (`un`/`pct`/`cx` sem fração)
- **Valor em R$**: `formatarReal()`/`formatarInputReal()`/`parsearInputReal()` de `formatarMoeda.ts` — nunca o valor cru da API
- **Busca por texto**: `useDebouncedValue()` (400ms) na `queryKey`, sem `useEffect` manual
- **Coluna "Material"**: sempre 3 colunas separadas (Código, Descrição, Unidade), nunca uma única
- **Erro real do backend**: `extrairMensagemErro()` em todo `onError` que pode receber `400`/`409`
- **Confirmação irreversível com revisão de dados**: modal de detalhes antes de confirmar (hoje só em Entrada — decisão pendente de estender a `confirmar-saida` e `aprovar`/`rejeitar`)

### Identidade visual

**Paleta do cliente** (definida por Gabriel Santos, 14/08/2026), centralizada em `src/theme.ts::cores`:
- `cores.primaria = '#333333'` (cinza-escuro/Charcoal) — botões, accent principal
- `cores.barraLateral = '#581538'` (vinho/bordô) — sidebar
- Fundo: branco quente `#FAF9F6`
- Tipografia: IBM Plex Sans (títulos/menu), IBM Plex Mono (colunas numéricas via `NumeroTabela`)

> A migração da paleta antiga (cobre `#B87333`/grafite) para a paleta oficial do cliente (`theme.ts` + páginas que tinham hex hardcoded) **já está commitada** no frontend (`:lipstick: aplica paleta oficial do cliente`, 17/08/2026) — pendência resolvida. Regra de arquitetura reforçada: nenhuma cor de marca pode ser hardcoded fora de `theme.ts`.

---

## 10. Deploy e ambientes

| | Backend | Frontend |
|---|---|---|
| Serviço | Render Web Service (Python nativo, sem Docker) | Render Static Site |
| URL | `https://engemil.onrender.com` | (Static Site do Render) |
| Build | `build.sh`: `pip install` → `collectstatic` → `migrate` → `seed_inicial` → `seed_teste_perfis` → `importar_materiais` → `seed_demo` | `npm run build` (Vite) |
| Banco | PostgreSQL gratuito do Render | — |
| Variável de build sensível | `.python-version` (não `runtime.txt` — convenção Heroku, não funciona no Render) | `VITE_API_URL` — só é "gravada" no bundle **durante o build**; trocar exige rebuild completo, não só restart |
| Estáticos | WhiteNoise + Gunicorn | SPA precisa de regra de rewrite (servir `index.html` para qualquer rota, senão F5 numa rota tipo `/materiais` dá 404) |
| JWT | `ACCESS_TOKEN_LIFETIME=8h`, `REFRESH_TOKEN_LIFETIME=7 dias` (estendido para não expirar durante demonstrações) | — |

**Docker completo** (Django + Postgres juntos) foi adiado conscientemente — decisão consciente de manter o deploy atual simples para o MVP, revisado numa etapa posterior do projeto.

**Atenção ao apresentar para o cliente**: o deploy em produção normalmente reflete a branch `main`; ambos os repositórios têm trabalho relevante em `develop` ainda não mesclado (ver [seção 2](#2-status-de-desenvolvimento)) — confirmar que o que está no ar é o que se pretende mostrar antes de uma demonstração.

---

## 11. Próximos passos técnicos

Em ordem sugerida de prioridade:

1. **Reverter o limite temporário de 10 materiais no Inventário** assim que a otimização de performance abaixo for feita — a regra combinada com o cliente é TODOS os materiais ativos (`InventarioService.LIMITE_TEMPORARIO_DEMO`)
2. **Performance geral do Inventário** — com ~979 materiais ativos por inventário, três frentes precisam de correção: paginar a listagem (não embutir `itens` completo só para contar "X/Y contados"), reduzir o payload do modal de detalhes, e paginar a tabela de contagem no frontend (hoje monta ~979 `InputNumber` simultâneos, causa de lentidão ao digitar)
3. Tela de Usuário no frontend com CRUD completo (hoje só leitura, usada em Select)
4. Refresh automático de token JWT no frontend (interceptor de 401 usando o `refresh_token`)
5. Validação de CNPJ no cadastro de Fornecedor (dígito verificador, mesmo padrão do CPF)
6. Decidir se o padrão "modal de detalhes antes de confirmar" (hoje só em Entrada) deve se estender para `confirmar-saida` de Solicitação e `aprovar`/`rejeitar` de Devolução
7. Rastrear "quem confirmou e quando" separadamente de "quem criou" em todas as ações de confirmação (hoje só Inventário faz isso)
8. `admin.py` para os apps `solicitacoes`, `entradas`, `devolucoes`, `inventario` (hoje só `core` está registrado)
9. Fechar gap de segurança de baixo risco: `PATCH` numa `Devolucao` própria do Encarregado ainda permite trocar `item_solicitacao` sem revalidar propriedade (só valida na criação)
10. Decidir se `seed_demo` deve continuar rodando em todo deploy (idempotente, mas roda a cada build) ou virar comando manual só para ambientes novos
11. **Testes automatizados** — nenhum foi escrito ainda, backend ou frontend. Priorizar: RN-010, saldo insuficiente, exclusividade de origem em `Movimentacao`, `EntradaJaConfirmadaError`, escopo individual do Encarregado, `DevolucaoJaAbertaError`/`SaldoDevolucaoInsuficienteError`, edição de Solicitação, ajuste pendente de Inventário
12. Dockerizar a aplicação completa (Django + Postgres) — adiado conscientemente
13. Revisar settings de produção (`SECURE_SSL_REDIRECT`/HSTS etc.) se o domínio final não for mais `*.onrender.com`

---

## 12. Pendências de negócio (para reunião com o cliente)

Lista completa em `PENDENCIAS_CONSOLIDADAS.md` do projeto (27 itens). Pontos mais relevantes:

| Pendência | Onde impacta |
|---|---|
| Método de custeio de saída (CMP, FIFO, último custo) — hoje usa "custo da última entrada" como placeholder | `core/domain/services.py` |
| Material deveria guardar um preço/valor de referência cadastral? — **já resolvido nesta sessão** (`Material.valor_unitario`) | `core/models.py` |
| Nomenclatura e ciclo de vida do status de Solicitação — manter versão simplificada (5 estados) ou adotar os 11 estados do documento v1.1? | `solicitacoes/models.py` |
| A data prevista da Solicitação precisa de horário, ou só data? — **campo saiu do formulário**, hoje é automático | Frontend — formulários de criação |
| Como será gerado o número de Solicitação/Entrada — manual ou sequencial automático? | Frontend — formulários de criação |
| Quem cria os usuários do sistema — autocadastro ou só Administrador designado? — **decidido**: só Admin/Engenheiro | `api/permissions.py` |
| Login por e-mail ou por CPF? — **decidido**: CPF | `core/models.py — Usuario.USERNAME_FIELD` |
| O padrão "modal de detalhes antes de confirmar" deveria se estender para confirmar-saída de Solicitação e aprovar/rejeitar de Devolução? | Frontend — UX de confirmação |
| Ações de confirmação deveriam rastrear separadamente "quem confirmou e quando"? — hoje só Inventário faz isso | `entradas`, `devolucoes` |
| Rejeição de devolução por motivo não relacionado a avaria deveria permitir retorno ao estoque? | `devolucoes/domain/services.py` |
| Material sem `categoria` e `localizacao` (RF-003) | `core/models.py — Material` |
| Solicitação sem campo `prioridade` (RF-008, DEC-01) | `solicitacoes/models.py` |
| Falta 5º tipo de origem em `Movimentacao` para "Ajuste" manual avulso (RF-018/UC-07) | `core/models.py — Movimentacao` (estrutural) |
| Entidades `CompraPendente` e `Contrato` não modeladas | Modelo conceitual — seção 12 do documento v1.1 |
| Encerramento de inventário exige 100% dos itens contados — **decidido**: só quando Engenheiro/Administrador encerra; Almoxarifado ainda precisa de 100% contado manualmente | `inventario/domain/services.py` |
| Todo item com divergência gera ajuste automático — deveria ter aprovação item a item? | `inventario/domain/services.py` |
| Reabertura de Solicitação — **decidido e revertido**: chegou a existir, foi removida por deixar itens/cabeçalho dessincronizados; Edição de Solicitação cobre a necessidade | `solicitacoes/domain/services.py` |
| Contexto de Demanda "tirado de uso por enquanto" — `Solicitacao.demanda` virou opcional; decisão final (manter opcional, tornar obrigatória de novo, ou remover de vez) ainda em aberto | `solicitacoes/models.py` |
| `ADMINISTRADOR`/`ENGENHEIRO` com acesso irrestrito a qualquer endpoint — confirmar se é o esperado | `api/permissions.py` |
| Encarregado restrito ao posto de lotação (não de responsabilidade) — **confirmado**: escopo é individual, não por posto | `api/permissions.py` |
| Perfis `COMPRAS` e `CONSULTA` sem mapeamento de acesso definido | `api/permissions.py` |
| Validação de CNPJ em Fornecedor (telefone já resolvido) | `core/validators.py` |

---

## 13. Decisões técnicas fechadas (não reabrir sem necessidade)

- Django + DRF, PostgreSQL, JWT — arquitetura definida em ART-04
- Domínio vive dentro de cada app (`domain/` separado de `models.py`), não é Clean Architecture total
- `core` nunca depende dos outros apps de domínio; `Movimentacao` mora em `core` por ser transversal
- FK entre apps via string (`'app.Model'`) para evitar import circular em Python
- Regra de origem única em `Movimentacao` validada em dupla camada (Python + `CheckConstraint` do banco)
- Regras de negócio com `CheckConstraint` no banco também precisam de `validate()` espelhado no serializer
- App `api/` centralizado, organizado internamente por bounded context
- Identidade visual: paleta oficial do cliente (`#333333` cinza-escuro + `#581538` vinho), definida por Gabriel Santos em 14/08/2026 — substitui a paleta placeholder anterior (cobre/grafite)
- Ambiente de demonstração no Render sem Docker (decisão consciente); Docker completo fica para etapa posterior
- Escopo do Encarregado é individual (`solicitante = request.user`), não por posto
- Reabertura de Solicitação **não existe** — foi implementada e depois removida (18/08/2026); Edição de Solicitação (`PATCH`/`PUT`) cobre a necessidade, sem o problema de itens/cabeçalho dessincronizados
- Encerrar Inventário com item não contado exige Engenheiro/Administrador; Almoxarifado só encerra sozinho com 100% contado
- Ajuste de Inventário que não coube no saldo atual não derruba o encerramento — fica pendente na `observacao` do item
- Observação da Solicitação é por item (`ItemSolicitacao.observacao`), não no cabeçalho
- `data_prevista` da Solicitação não é mais input do usuário — nasce igual a `data_solicitacao`
- Login por CPF, nunca e-mail ou `nome.sobrenome`
