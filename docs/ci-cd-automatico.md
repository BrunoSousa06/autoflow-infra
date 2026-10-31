# Início automático do CD

Os workflows de CD recebem `push` em `develop` ou `main`. O gate valida a branch, o repositório e o SHA e, quando `AUTO_CD_ENABLED=true` no Environment de destino, aguarda a conclusão `success` da CI correspondente ao mesmo commit. Variable ausente ou diferente de `true` desabilita o caminho automático; falha, cancelamento, `skipped`, divergência ou timeout bloqueia o Plan. A pipeline não cria Variables, Secrets, Environments ou regras de proteção.

No repositório `autoflow-infra`, essa configuração habilita separadamente as três pipelines existentes (VPC/EKS, HTTP API Gateway e New Relic) após a CI comum validar os respectivos roots. Cada CD continua independente e executa seu próprio Plan; os seis Terraform roots permanecem separados.

O gate usa `actions:read` para consultar a API do GitHub por até 30 minutos. Confirma o nome e o evento `push` da CI, o repositório, a branch, o SHA e a conclusão. A leitura da Variable usa a API do Environment: resposta 404 mantém o CD automático desabilitado; outros erros encerram o gate antes de acessar AWS. O checkout confirma o SHA validado. PRs e branches `feature/**` executam apenas CI; `main` precisa estar protegida.

No repositório `autoflow-infra`, `AUTO_CD_ENABLED` habilita separadamente os Plans automáticos de VPC/EKS, API Gateway e
New Relic para o Environment correspondente. Cada workflow mantém seu próprio Terraform State e Plan. Os Plans de
VPC/EKS e New Relic gerenciam leases temporários para acesso do runner ao endpoint EKS.

O caminho automático não executa Apply. Apply exige `workflow_dispatch` com `apply=true` e
`TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`; o job usa o GitHub Environment selecionado. Configure Required reviewers e
restrições de branch para proteger os deployments. A aprovação de um Plan não autoriza Apply.

## Configuração externa

- Para habilitar homologação, definir `AUTO_CD_ENABLED=true` no Environment `homolog`; para habilitar produção, definir o mesmo nome separadamente em `production`. Valor ausente ou diferente de `true` mantém o respectivo ambiente desabilitado.
- Fazer a configuração separadamente em cada repositório. Em `autoflow-infra`, uma Variable por Environment habilita as três pipelines independentes desse repositório.
- A configuração exige apenas uma Variable não sensível; não exige Secret novo nem ID de conta. Os CD jobs continuam reutilizando as configurações AWS, States, criptografia e gates já existentes em cada Environment.

Configure as proteções nativas dos Environments e a proteção de `main`; o código não cria essas configurações. O caminho
automático libera somente Plan após a CI aprovada; Apply é um dispatch separado.
