# Root Terraform New Relic

Este root gerencia exclusivamente `helm_release.newrelic_kubernetes`, dashboards, alert policy/conditions NRQL e Synthetic. Não cria nem importa VPC, EKS, node group, RDS ou API Gateway. O EKS é consultado por data sources AWS com o nome fornecido externamente; o Secret Kubernetes é apenas validado e referenciado pelo nome.

## State e providers

- Backend S3 independente: mesmo bucket do repositório, key `homolog/newrelic/terraform.tfstate` ou `production/newrelic/terraform.tfstate`, configurada por `AWS_TF_STATE_KEY_NEWRELIC`.
- Providers travados: AWS `5.100.0`, Helm `3.3.0` e New Relic `3.100.5`. O lockfile mantém checksums `h1` e `zh` existentes, inclusive plataformas Linux e Windows.
- Inicialização local para validação sem backend: `terraform -chdir=infra/newrelic init -backend=false -input=false -lockfile=readonly`.

## Configuração externa

Reutiliza `AWS_REGION`, `AWS_EXPECTED_ACCOUNT_ID`, credenciais AWS existentes, `AWS_TERRAFORM_STATE_BUCKET`, `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE` e `TERRAFORM_APPLY_APPROVAL_CONFIGURED`. Adiciona a variable necessária `AWS_TF_STATE_KEY_NEWRELIC`. O nome do cluster EKS é descoberto por consulta AWS após validar conta/região; não configure `EKS_CLUSTER_NAME`. Os inputs New Relic já existentes (`ENABLE_NEWRELIC_KUBERNETES`, `ENABLE_NEWRELIC_ACCOUNT_RESOURCES`, account/region/API key, Synthetic e consultas opcionais) passam a ser consumidos por `newrelic.yml`. Configure-os por Environment (`homolog`/`production`); `NEW_RELIC_API_KEY` é User API key e não é a License Key. O pipeline também precisa dessa API key para confirmar ausência de objetos remotos antes de criar.

O namespace `default`, Secret `newrelic-license`/chave `licenseKey`, release `newrelic-kubernetes` e chart `nri-bundle` versão `8.0.32` preservam a configuração existente. Antes de habilitar qualquer recurso New Relic, o workflow exige EKS e node groups `ACTIVE`, conectividade Kubernetes, Deployments `autoflow-backend`/`autoflow-frontend` com todas as réplicas disponíveis e Services internos existentes. Para `ENABLE_NEWRELIC_KUBERNETES=true`, também exige Secret não vazio.

O inventário remoto pagina dashboards via NerdGraph e alertas, condições e Synthetic via endpoints REST. Falhas HTTP, GraphQL, cursores inválidos e respostas REST incompatíveis bloqueiam o Plan/Apply; não são tratados como inventário vazio.

## Execução

`New Relic Pipeline` valida em PRs, executa Plan somente em `develop`/`main`, criptografa e publica artifact vinculado ao commit, e aplica apenas por `workflow_dispatch` com `apply=true` e aprovação efetiva do Environment. `homolog` é selecionado em `develop`, `production` em `main`. Plan destrutivo requer `allow_destructive=true`, reviewers e configuração de aprovação no GitHub. Nenhum deploy executa migração de state.

Antes do primeiro uso, seguir [reconstrução do Learner Lab](../../docs/reconstrucao-learner-lab.md) para cenário A ou o [runbook de migração](../../docs/newrelic-state-migration.md) para cenário B. A pipeline bloqueia state antigo com recursos New Relic, ownership duplicado, objetos remotos conhecidos e inventário remoto inconclusivo. Ela não faz import, `state rm`, `state mv` nem recovery automaticamente.
