# Primeiro provisionamento do EKS após reset

O workflow `Pipeline` e o root `infra/` gerenciam somente VPC, rede, EKS e node group. New Relic não é planejado nem aplicado neste root; sua instalação ocorre separadamente em `infra/newrelic/` depois que EKS, aplicação e Secret estão prontos.

## Sequência após reset do Learner Lab

1. Confirme/reabra o Learner Lab e execute o workflow `Pipeline` em `develop` via `workflow_dispatch` com `apply` habilitado. Antes do Plan, o preflight read-only verifica que as Cluster/Node Roles existem, são diferentes, confiam em `eks.amazonaws.com`/`ec2.amazonaws.com` e têm as AWS managed policies requeridas. Se o cluster já existir, a role efetiva deve corresponder à configurada; divergência bloqueia a execução e exige reconstrução controlada. O Apply aprovado cria/reconcilia VPC, cluster e node group. Em `main`, use `workflow_dispatch`; a aprovação do Environment `production` continua obrigatória.
2. Execute os pipelines RDS e Lambda nessa ordem; Lambda consome os States EKS e RDS.
3. Execute `Migração HTTP API` em `autoflow-infra/develop`. Exige EKS/node group ativos e Lambda existente; pode criar VPC Link e ALB antes dos workloads da aplicação.
4. Execute o pipeline de `autoflow/develop`. Ele exige RDS e API Gateway, descobre o endpoint e o cluster, e sincroniza a License Key existente para Secrets Manager e Secret Kubernetes; em caso de falha, para sem aplicar a aplicação.
5. Execute uma vez `New Relic Pipeline` por `workflow_dispatch` em `develop`, com `apply=true`, após revisão do Plan. O workflow opera somente no root `infra/newrelic/`, valida conta/região, EKS/node groups, Deployments e Services da aplicação; quando Kubernetes New Relic está habilitado, também valida o Secret `newrelic-license`/`licenseKey`. Não é necessário reaplicar VPC/EKS.

Se Deployments/Services não estiverem prontos, ou se o Secret/License Key exigido estiver ausente, vazio ou ilegível, a etapa de validação falha e bloqueia o Apply New Relic. Falhas AWS e inventário remoto ambíguo também bloqueiam a operação. Plan criptografado, checksums, GPG, lockfile readonly, guard destrutivo e Required reviewers são independentes por workflow/root.

No cenário A, confirmar que os objetos New Relic e os endereços em ambos os states estão ausentes; não há migração. No cenário B, o workflow New Relic bloqueia recursos ainda registrados no root legado e não remove/importa state. Siga o [runbook de migração](newrelic-state-migration.md) com autorização explícita. O workflow principal também bloqueia Plans que tentem destruir recursos New Relic residuais.

## Passos manuais

- Reativar o Learner Lab e garantir que as GitHub Actions Variables/Secrets, AWS credentials temporárias e Required reviewers dos Environments estejam válidos.
- Disparar os workflows em sequência: Bootstrap, VPC/EKS, RDS, Lambda, API Gateway, aplicação e New Relic. Não é necessário executar o Apply de VPC/EKS duas vezes.
- Se a License Key existente diferir entre GitHub Secrets e AWS Secrets Manager, interromper e fazer a rotação controlada indicada pelo pipeline `autoflow`; não criar uma segunda key/variável.

Após reset do AWS Academy Learner Lab, reexecute as pipelines CI/CD nesta sequência para provisionar novamente o ambiente.
