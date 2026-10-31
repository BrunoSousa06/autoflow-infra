# Root Terraform New Relic

Este root gerencia exclusivamente `helm_release.newrelic_kubernetes`, dashboards, alert policy/conditions NRQL e Synthetic. Não cria nem importa VPC, EKS, node group, RDS ou API Gateway. O EKS é consultado por data sources AWS com o nome fornecido externamente; o Secret Kubernetes é apenas validado e referenciado pelo nome.

## Recursos de observabilidade declarados

- `ENABLE_NEWRELIC_KUBERNETES=true` habilita o chart `nri-bundle`, incluindo coleta Kubernetes e Fluent Bit para logs do
  namespace configurado. A aplicação instala o agente APM Java e emite eventos de OS e falhas de integração.
- `ENABLE_NEWRELIC_ACCOUNT_RESOURCES=true` declara dashboard privado e condições NRQL para OS criadas/dia, duração por
  etapa, latência APM, CPU/memória, falhas de processamento e integrações. Synthetic exige URL e locations fornecidas em
  conjunto; quando habilitado, o monitor é configurado para executar a cada cinco minutos.
- O dashboard e as condições só são criados quando a flag de recursos de conta está ativa. Consultas opcionais controlam
  widgets/alertas de disponibilidade, CPU e memória. O código não comprova que as flags estejam ativas ou que os recursos
  estejam implantados.
- O filtro dos widgets APM no dashboard usa `environment`, enquanto as condições APM usam `tags.environment`. A
  compatibilidade desses atributos não foi verificada no New Relic. Este root também não declara destino/workflow de
  notificação; no root API Gateway, `alarm_actions` é vazio por padrão.

Na consulta somente-leitura ao GitHub em 31/10/2026, as flags `ENABLE_NEWRELIC_KUBERNETES` e
`ENABLE_NEWRELIC_ACCOUNT_RESOURCES` estavam `true` em `homolog` e ausentes em `production`. Isso descreve a configuração
dos Environments, não comprova Apply, ingestão ou recursos ativos. A variável `ENABLE_NEWRELIC_APM` da aplicação estava
`true` nos dois Environments.

Os eventos `AutoFlowOrderCreated`, `AutoFlowOrderStageCompleted`, `AutoFlowOrderProcessingFailure` e
`AutoFlowIntegrationFailure` são emitidos pela aplicação e carregam o atributo `environment`. Logs JSON incluem
`request.id` e, quando disponíveis, `trace.id`/`span.id`. Configuração versionada e testes não comprovam ingestão, abertura
de incidentes, entrega de notificações ou execução de Synthetic.

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

O workflow `.github/workflows/ci.yml` valida automaticamente New Relic em PRs para `develop`/`main` e pushes para `develop`, `main` e `feature/**`, sem acesso AWS. `New Relic Pipeline` recebe `push` para `develop`/`main` e `workflow_dispatch`. O caminho automático espera sucesso da CI para o mesmo SHA e só libera Plan quando `AUTO_CD_ENABLED=true` no Environment; a Variable estava ausente em `homolog` e `production` na consulta somente-leitura de 31/10/2026, então o caminho estava desabilitado. `develop` seleciona `homolog`; `main`, `production`. O caminho automático não executa Apply. Apply requer dispatch com `apply=true`, aprovação do Environment selecionado e `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`; essa Variable estava `false` nos dois Environments e bloqueava Apply. Regrasets de branch, Required reviewers e políticas `develop`/`main` estavam ativos na mesma consulta. O Plan é criptografado e publicado em artifact vinculado ao commit. `approve_reconciliation` só pode ser habilitado por dispatch e gera imports declarativos incluídos no Plan; scripts não alteram State. Exclusões e substituições continuam sujeitas aos guards existentes e à aprovação explícita.

Antes do primeiro uso, confirmar conta, ambiente e ownership. A pipeline bloqueia State legado, ownership duplicado, identidade ambígua, respostas incompletas e inventário inconclusivo. Divergência exige `workflow_dispatch` com `approve_reconciliation=true` e revisão do Plan; imports são declarativos e incluídos no mesmo Plan aprovado. A reconciliação não executa `state rm`, `state mv`, importação fora do Terraform ou Apply automático.
