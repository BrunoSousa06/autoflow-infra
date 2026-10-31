# Root Terraform New Relic

Este root gerencia exclusivamente `helm_release.newrelic_kubernetes`, dashboards, alert policy/conditions NRQL e Synthetic. Não cria nem importa VPC, EKS, node group, RDS ou API Gateway. O EKS é consultado por data sources AWS com o nome fornecido externamente; o Secret Kubernetes é apenas validado e referenciado pelo nome.

## Recursos de observabilidade declarados

`ENABLE_NEWRELIC_KUBERNETES` (default `false`) habilita o chart `nri-bundle`, incluindo coleta Kubernetes e Fluent Bit
para logs do namespace configurado. A aplicação configura o agente APM Java e emite eventos de OS e integração.

`ENABLE_NEWRELIC_ACCOUNT_RESOURCES` (default `false`) habilita o dashboard privado e as condições NRQL para OS criadas/dia,
duração por etapa, latência APM, CPU/memória, falhas de processamento e integrações. Consultas opcionais definem widgets
e alertas de disponibilidade, CPU e memória. Synthetic requer URL e locations; o monitor é configurado para executar a
cada cinco minutos. Os recursos são provisionados pelo Apply do root.

Os widgets APM do dashboard filtram `environment`; as condições APM filtram `tags.environment`. Ajuste as consultas de
acordo com os atributos emitidos pelo agente. Este root não declara workflow/destino de notificação; no root API Gateway,
`alarm_actions` é vazio por padrão.

A aplicação emite `AutoFlowOrderCreated`, `AutoFlowOrderStageCompleted`, `AutoFlowOrderProcessingFailure` e
`AutoFlowIntegrationFailure`, todos com o atributo `environment`. Os logs JSON incluem `request.id` e, quando disponíveis,
`trace.id`/`span.id`.

## State e providers

- Backend S3 independente: bucket e key exclusivos fornecidos por Variables do GitHub Environment selecionado. A key deve começar com `homolog/` ou `production/`; seu sufixo é definido externamente e não é fixado neste root.
- Este root não cria o bucket. Se estiver ausente, execute primeiro o [bootstrap S3 isolado](../../docs/state-bucket-bootstrap.md); o workflow New Relic não faz bootstrap implícito.
- Providers travados: AWS `5.100.0`, Helm `3.3.0` e New Relic `3.100.5`. O lockfile mantém checksums `h1` e `zh` existentes, inclusive plataformas Linux e Windows.
- Inicialização local para validação sem backend: `terraform -chdir=infra/newrelic init -backend=false -input=false -lockfile=readonly`.

## Configuração externa

Reutiliza `AWS_REGION`, `AWS_EXPECTED_ACCOUNT_ID`, credenciais AWS, `AWS_TERRAFORM_STATE_BUCKET`, `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE` e `TERRAFORM_APPLY_APPROVAL_CONFIGURED`. Configure `AWS_TF_STATE_KEY_NEWRELIC` e os demais valores próprios em cada GitHub Environment (`homolog` ou `production`). O preflight verifica os valores resolvidos pelos contextos `vars`/`secrets`, sem consultar APIs administrativas para enumerar seu escopo. O nome do cluster EKS é descoberto após validar conta/região; não configure `EKS_CLUSTER_NAME`. Os inputs New Relic existentes (`ENABLE_NEWRELIC_KUBERNETES`, `ENABLE_NEWRELIC_ACCOUNT_RESOURCES`, account/region/API key, Synthetic e consultas opcionais) são consumidos por `newrelic.yml`; `NEW_RELIC_API_KEY` é User API key, não License Key, e é exigida para confirmar ausência de objetos remotos antes de criar.

O namespace `default`, Secret `newrelic-license`/chave `licenseKey`, release `newrelic-kubernetes` e chart `nri-bundle` versão `8.0.32` preservam a configuração existente. Antes de habilitar qualquer recurso New Relic, o workflow exige EKS e node groups `ACTIVE`, conectividade Kubernetes, Deployments `autoflow-backend`/`autoflow-frontend` com todas as réplicas disponíveis e Services internos existentes. Para `ENABLE_NEWRELIC_KUBERNETES=true`, também exige Secret não vazio.

O inventário remoto pagina dashboards via NerdGraph e alertas, condições NRQL e Synthetic via endpoints REST. Valida conta e ambiente, relaciona IDs somente em arquivos temporários protegidos e bloqueia falhas HTTP, GraphQL, cursores inválidos, páginas incompletas, duplicidade e identidades divergentes. `State` com `instances: []` não representa objeto existente.

## Execução

O workflow `.github/workflows/ci.yml` valida o root em Pull Requests para `develop`/`main` e pushes para `develop`, `main`
e `feature/**`, sem acesso AWS. `New Relic Pipeline` recebe `push` em `develop`/`main` e `workflow_dispatch`; o caminho
automático exige `AUTO_CD_ENABLED=true` e CI bem-sucedida para o mesmo SHA e executa somente Plan. Apply exige dispatch
com `apply=true` e `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`; o job usa o Environment selecionado. Configure Required
reviewers e restrições de branch para proteger o deployment. O Plan é criptografado e publicado em artifact vinculado ao
commit. `approve_reconciliation` gera imports declarativos incluídos no Plan; scripts não alteram State. Exclusões e
substituições exigem autorização e revisão do Plan.

Antes do primeiro uso, confirmar conta, ambiente e ownership. A pipeline bloqueia State legado, ownership duplicado, identidade ambígua, respostas incompletas e inventário inconclusivo. Divergência exige `workflow_dispatch` com `approve_reconciliation=true` e revisão do Plan; imports são declarativos e incluídos no mesmo Plan aprovado. A reconciliação não executa `state rm`, `state mv`, importação fora do Terraform ou Apply automático.
