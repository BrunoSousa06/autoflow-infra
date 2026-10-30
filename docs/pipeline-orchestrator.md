# Orquestrador de pipelines AutoFlow — Fase 1

## Escopo e garantias

O orquestrador é uma ferramenta local de consulta para os repositórios configurados `autoflow-fiap/autoflow-infra`, `autoflow-fiap/autoflow-db`, `autoflow-fiap/autoflow-lambda` e `autoflow-fiap/autoflow`. A implementação aceita apenas os ambientes `homolog` e `production` e as ações `status`, `validate` e `report`.

A Fase 1 é estritamente somente leitura em GitHub e AWS. O cliente executa `gh api --method GET` para endpoints fixos da allowlist. Não chama `gh workflow run`, não grava Variables/Secrets/Environments, não aprova deployments, não usa AWS CLI e não executa Terraform. A ferramenta não substitui os gates de segurança, Required reviewers ou aprovações nativas das pipelines.

O orquestrador não consulta recursos nem States na AWS. Uma execução concluída é apenas o resultado informado pelo GitHub Actions e não prova que recursos foram provisionados, que o State remoto existe ou que a aplicação está saudável.

## Requisitos locais

- Windows PowerShell 5.1 ou posterior compatível com Windows PowerShell.
- GitHub CLI (`gh`) instalado e autenticado pelo mecanismo aprovado para a estação/usuário.
- Python 3 acessível como `python`, para executar `scripts/terraform_state_contract.py` sem dependências externas.
- Pester para executar os testes. A suíte foi verificada com Pester 3.4, já disponível no ambiente de desenvolvimento. O orquestrador não instala módulos globalmente.

O programa não cria nem administra um PAT. `gh` usa a sessão já autenticada no ambiente. Não copie tokens para parâmetros, arquivos, exemplos ou logs. A API de Secrets é consultada somente para obter nomes e metadados; nenhum endpoint que retorne valores de Secrets é chamado.

## Permissões GitHub

O usuário autenticado no `gh` precisa ter acesso de leitura a cada um dos quatro repositórios. Para tokens fine-grained ou GitHub Apps, conceda somente as permissões de leitura necessárias, limitadas aos quatro repositórios:

- `Metadata: read` para identificar os repositórios.
- `Contents: read` para consultar branches.
- `Actions: read` para listar workflows, execuções, jobs e pending deployments.
- `Environments: read` para consultar Environment, reviewers, branch policies, Variables e nomes de Secrets.

As permissões efetivamente exigidas podem variar com o tipo de credencial e as regras da organização. Um `403` é apresentado como `ACCESS_DENIED`; rate limit é `RATE_LIMIT`. Não reduza ou altere os gates para contornar falta de permissão. Um `404` no endpoint do repositório pode significar ausência ou invisibilidade de um repositório privado, portanto o orquestrador o classifica como `NOT_FOUND_OR_NOT_VISIBLE`, sem declarar que está ausente. A ausência de um Environment só é confirmada se o inventário de Environments responder validamente e não incluir o nome solicitado; um `404` direto é `UNKNOWN`.

## Como executar

### Instalação local

Não há pacote ou instalador: a ferramenta é executada diretamente do checkout de `autoflow-infra` e não instala dependências globais. Disponibilize `gh` e Python 3 no `PATH`; para executar os testes, use uma instalação Pester já autorizada no escopo do usuário. Autentique o `gh` pelo procedimento aprovado para a estação antes da consulta.

Execute os comandos a partir da raiz de `autoflow-infra`:

```powershell
.\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action status
.\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action validate
.\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action report
.\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment production -Action report
```

### `status`

Para o ambiente selecionado, consulta o repositório, a branch correspondente, os workflows e a execução mais recente de cada workflow. Consulta os jobs dessa execução. Os mapeamentos observados nos workflows são `develop` para `homolog` e `main` para `production`.

São exibidos ID e URL da execução, branch, SHA do commit, `status`, `conclusion` e jobs com conclusão `failure`, `cancelled` ou `skipped`. `queued`, `in_progress`, `waiting` e `completed` permanecem estados de execução distintos. `failure`, `cancelled` e `skipped` permanecem conclusões distintas. Se a API não retornar uma conclusão, o campo aparece como `not_reported`; não é inferido sucesso.

Quando o run ou um job está `waiting`, o orquestrador consulta também `GET /actions/runs/{run_id}/pending_deployments`. Só declara aprovação pendente quando a API retorna um Environment pendente. O resultado inclui nome do Environment, quantidade de reviewers e o sinalizador `current_user_can_approve`; não lista identidades nem aprova. Se a API não confirmar a pendência ou estiver inacessível, `waiting` permanece distinto e o motivo não é inferido.

### `validate`

Mesmo quando `-Environment homolog` é selecionado, a validação consulta os dois GitHub Environments, `homolog` e `production`, nos quatro repositórios. Para cada Environment verifica:

- Repositório, branch associada e existência do GitHub Environment.
- Required reviewers retornados pela API e política de branches para a branch mapeada.
- Presença de Variables exigidas pelos workflows observados, nomes dos Secrets obrigatórios e valor de `TERRAFORM_APPLY_APPROVAL_CONFIGURED`. O valor exato `false` é reportado como bloqueio operacional deliberado (`OPERATIONAL_BLOCKED`); não autoriza Apply nem altera os gates. Valores ausentes ou vazios são inconsistências, assim como qualquer valor diferente de `true`/`false`.
- Formato de conta e região, valores necessários e consistência de conta, bucket e região entre os seis roots.
- As seis State Keys, as referências entre produtor/consumidor e o isolamento homolog/production.

O contrato de State é montado em memória a partir de Variables consultadas e validado por execução do comando existente `python scripts/terraform_state_contract.py <arquivo-temporario>`. O orquestrador não duplica nem altera as regras de `terraform_state_contract.py`; o arquivo temporário UTF-8 sem BOM é removido ao terminar e não contém Secrets ou tokens. A consulta não lê buckets, objetos S3 nem conteúdo de Terraform State.

O mapeamento observado das seis State Keys está abaixo. Para raízes consumidoras, as referências vêm das Variables usadas pelos workflows/Terraform. Na aplicação, `infra/data.tf` usa `var.rds_state_key`, variável obrigatória em `infra/vars.tf`; os jobs Plan e Apply do workflow definem `TF_VAR_rds_state_key` a partir de `AWS_RDS_STATE_KEY` e exigem essa Variable no Environment. Assim, o default literal `rds/terraform.tfstate` anteriormente usado pelo Orchestrator não representava o fluxo do deploy.

| Root | Repositório / Variable da key | Referências consultadas |
|---|---|---|
| VPC/EKS (`vpc_eks`) | `autoflow-infra` / `AWS_TF_STATE_KEY_INFRA` | — |
| RDS (`rds`) | `autoflow-db` / `AWS_TF_STATE_KEY` | `AWS_INFRA_STATE_KEY` → VPC/EKS |
| Lambda (`lambda`) | `autoflow-lambda` / `AWS_TF_STATE_KEY` | `AWS_INFRA_STATE_KEY` → VPC/EKS; `AWS_RDS_STATE_KEY` → RDS |
| Aplicação (`application`) | `autoflow` / `AWS_TF_STATE_KEY` | `AWS_RDS_STATE_KEY` → RDS |
| API Gateway (`api_gateway`) | `autoflow-infra` / `AWS_TF_STATE_KEY_GATEWAY` | `AWS_TF_STATE_KEY_INFRA` → VPC/EKS |
| New Relic (`newrelic`) | `autoflow-infra` / `AWS_TF_STATE_KEY_NEWRELIC` | `AWS_TF_STATE_KEY_INFRA` → VPC/EKS |

As State Keys do RDS e as referências VPC/EKS → DB e VPC/EKS → Lambda/RDS são obtidas das Variables por Environment; o contrato verifica que as referências coincidam com os produtores. Não foi identificada divergência efetiva entre a aplicação e o State Key do RDS no fluxo declarado localmente. A validação também consulta `production` ainda que o workflow de um repositório não tenha atualmente um job de Apply de produção.

Não são consultados valores de Secrets. Um nome de Secret presente não prova que o valor existe, está atualizado ou é aceito pelo serviço consumidor. Para Variable ou Secrets list inacessível, o resultado é `UNKNOWN` ou `ACCESS_DENIED`, nunca ausência presumida.

### `report` e exportação local

`report` consolida repositórios, branches, estado de workflows, resultados mais recentes, estados `waiting` expostos, problemas de configuração, dependências e recomendações para revisão manual.

Para gravar arquivos locais JSON e/ou Markdown:

```powershell
.\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 `
  -Environment homolog `
  -Action report `
  -JsonPath "$env:TEMP\autoflow-homolog.json" `
  -MarkdownPath "$env:TEMP\autoflow-homolog.md"
```

As pastas de destino precisam existir e os arquivos de destino ainda não podem existir; isso evita sobrescrever arquivos locais. Os arquivos usam UTF-8 sem BOM e contêm nomes de Secrets, nunca valores de Secrets, credenciais ou tokens. O relatório omite valores de Variables; registra nomes e achados relevantes. A existência de sucesso de workflow não é convertida em afirmação de provisionamento AWS.

### `-DryRun`

`-DryRun` lista as consultas planejadas para o ambiente e a ação, sem chamar `gh`, sem acessar AWS e sem gravar relatórios:

```powershell
.\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action report -DryRun
```

O plano mostra endpoints como modelos quando seus IDs dependem das respostas futuras. Não mostra nem armazena credenciais.

## Interpretação e códigos de saída

| Código | Significado |
|---:|---|
| `0` | Consultas concluídas sem inconsistências conhecidas. Não implica recursos provisionados. |
| `1` | Inconsistência de configuração confirmada por resposta válida. |
| `2` | Parâmetro inválido, ação não suportada ou opção de exportação incompatível. |
| `3` | Consulta/API indisponível, falta de permissão, rate limit, timeout, resposta inválida ou informação desconhecida necessária. |
| `4` | Bloqueio operacional deliberado: `TERRAFORM_APPLY_APPROVAL_CONFIGURED=false`; Apply segue bloqueado pelos gates do workflow. |

Estados como `MISSING_ENVIRONMENT` significam ausência confirmada em inventário válido depois de identificar o repositório. `ACCESS_DENIED`, `RATE_LIMIT`, `TIMEOUT`, `API_UNAVAILABLE`, `INVALID_RESPONSE` e `UNKNOWN` não são traduzidos em configuração ausente. O resultado global dá precedência a falhas/indisponibilidades de consulta sobre inconsistências encontradas em dados parciais.

## Limitações da Fase 1

- Nenhuma consulta à AWS, S3, Terraform State, EKS, RDS, Lambda ou API Gateway é executada.
- Somente a execução mais recente por workflow é consultada; histórico completo, logs e artifacts não são baixados.
- A API pode mostrar `waiting` sem dados de pending deployment; nesses casos, a aprovação não é presumida. O endpoint pode não estar acessível com a sessão atual.
- A configuração de proteção é observada pela API no momento da consulta. A ferramenta não testa se um usuário consegue aprovar nem substitui Required reviewers nativos.
- Policies customizadas são consideradas isoladas quando permitem somente a branch mapeada. Para `protected_branches`, a ferramenta verifica a proteção da branch esperada e da branch mapeada ao outro Environment; branches protegidas adicionais não são inventariadas nesta fase.
- O conteúdo retornado depende das permissões da sessão existente no GitHub CLI. Dados ocultos ou indisponíveis não recebem aprovação implícita.
- A configuração de GitHub Environment dos repositórios DB e Lambda e a política efetivamente configurada no GitHub não são presumidas a partir do código local.

## Evolução planejada para a Fase 2

A Fase 2 poderá propor ações de coordenação somente após uma especificação independente, aprovação explícita e revisão dos controles de autorização e auditoria. Não está implementada nesta Fase 1: não há dispatch, Apply, alteração de configuração ou aprovação automática.

## Testes locais

Sem instalar dependências globais:

```powershell
Invoke-Pester -Path .\scripts\orchestration\tests\AutoFlow.Orchestration.Tests.ps1 -Verbose
```

Os testes usam transportes simulados; não consultam GitHub ou AWS. Eles cobrem parsing HTTP, estados dos workflows/jobs, paginação, validação dos dois ambientes, isolamento de State Keys, relatórios e ausência de ações de escrita.
