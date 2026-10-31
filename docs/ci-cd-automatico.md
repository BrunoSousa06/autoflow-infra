# Início automático do CD

Os workflows de CD recebem `push` em `develop` ou `main`. O gate valida a branch, o repositório e o SHA e lê a Repository Variable selecionada pela branch: `AUTO_CD_ENABLED_HOMOLOG` para `develop` ou `AUTO_CD_ENABLED_PRODUCTION` para `main`. Somente o valor literal `true` habilita o caminho automático e leva o gate a aguardar `success` da CI correspondente ao mesmo commit. Variável ausente ou diferente de `true` desabilita o caminho automático; falha, cancelamento, `skipped`, divergência ou timeout bloqueia o Plan. A pipeline não cria Variables, Secrets, Environments ou regras de proteção.

No repositório `autoflow-infra`, essa configuração habilita separadamente as três pipelines existentes (VPC/EKS, HTTP API Gateway e New Relic) após a CI comum validar os respectivos roots. Cada CD continua independente e executa seu próprio Plan; os seis Terraform roots permanecem separados.

O gate usa `actions:read` para consultar a API de Actions por até 30 minutos e aguardar a CI. Confirma o nome e o evento `push`, o repositório, a branch, o SHA e a conclusão. As flags são injetadas pelo contexto `vars`, sem consulta administrativa a Environments. O checkout confirma o SHA validado. PRs e branches `feature/**` executam apenas CI; `main` precisa estar protegida.

No repositório `autoflow-infra`, `AUTO_CD_ENABLED_HOMOLOG` e `AUTO_CD_ENABLED_PRODUCTION` habilitam separadamente os
Plans automáticos de VPC/EKS, API Gateway e New Relic para a branch correspondente. Cada workflow mantém seu próprio Terraform State e Plan. Os Plans de
VPC/EKS e New Relic gerenciam leases temporários para acesso do runner ao endpoint EKS.

O caminho automático não executa Apply. Apply exige `workflow_dispatch` com `apply=true` e
`TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`; o job usa o GitHub Environment selecionado. Configure Required reviewers e
restrições de branch para proteger os deployments. A aprovação de um Plan não autoriza Apply.

## Configuração externa

- Para habilitar homologação, definir a Repository Variable `AUTO_CD_ENABLED_HOMOLOG=true`; para habilitar produção, definir separadamente `AUTO_CD_ENABLED_PRODUCTION=true`. Valor ausente ou diferente de `true` mantém o respectivo ambiente desabilitado.
- Fazer a configuração no escopo Repository. Em `autoflow-infra`, cada flag por branch habilita os Plans automáticos das três pipelines independentes desse repositório.
- As flags são Variables não sensíveis; não exigem Secret novo nem ID de conta. Os CD jobs continuam reutilizando as configurações AWS, States, criptografia e gates já existentes em cada Environment.

Configure as proteções nativas dos Environments e a proteção de `main`; o código não cria essas configurações. O caminho
automático libera somente Plan após a CI aprovada; Apply é um dispatch separado.
