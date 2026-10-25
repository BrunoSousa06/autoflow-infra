# Primeiro provisionamento do EKS após reset

O workflow `Pipeline` e o root `infra/` gerenciam somente VPC, rede, EKS e node group. New Relic não é planejado nem aplicado neste root; sua instalação ocorre separadamente em `infra/newrelic/` depois que o cluster está ativo e a aplicação sincronizou o Secret.

## Sequência após reset do Learner Lab

1. Confirme/reabra o Learner Lab e execute o workflow `Pipeline` em `develop` via `workflow_dispatch` com `apply` habilitado. O Apply aprovado cria/reconcilia VPC, cluster e node group. Em `main`, use `workflow_dispatch`; a aprovação do Environment `production` continua obrigatória.
2. Aguarde o Apply terminar e o node group ficar operacional. Execute o pipeline existente do repositório `autoflow` na branch/environment correspondente. Ele prepara kubeconfig e sincroniza automaticamente a License Key existente do GitHub Secret para AWS Secrets Manager e para o Secret Kubernetes; em caso de falha, esse pipeline para sem aplicar a aplicação.
3. Execute uma vez `New Relic Pipeline` por `workflow_dispatch` em `develop`, com `apply=true`, após revisão do Plan. O workflow opera somente no root `infra/newrelic/`, valida conta/região, EKS/node groups e Secret `newrelic-license`/`licenseKey` antes de instalar `nri-bundle` quando habilitado. Não é necessário reaplicar VPC/EKS.

Se o cluster existir, mas o Secret/License Key estiver ausente, vazio ou ilegível, a etapa de validação falha e bloqueia o Apply New Relic. Falhas AWS e inventário remoto ambíguos bloqueiam a operação. Plan criptografado, checksums, GPG, lockfile readonly, guard destrutivo e Required reviewers são independentes por workflow/root.

No cenário A, confirmar que os objetos New Relic e os endereços em ambos os states estão ausentes; não há migração. No cenário B, o workflow New Relic bloqueia recursos ainda registrados no root legado e não remove/importa state. Siga o [runbook de migração](newrelic-state-migration.md) com autorização explícita. O workflow principal também bloqueia Plans que tentem destruir recursos New Relic residuais.

## Passos manuais

- Reativar o Learner Lab e garantir que as GitHub Actions Variables/Secrets, AWS credentials temporárias e Required reviewers dos Environments estejam válidos.
- Disparar os workflows em sequência: VPC/EKS; RDS, Lambda e aplicação conforme dependências; por fim New Relic. Não é necessário executar o Apply de VPC/EKS duas vezes.
- Se a License Key existente diferir entre GitHub Secrets e AWS Secrets Manager, interromper e fazer a rotação controlada indicada pelo pipeline `autoflow`; não criar uma segunda key/variável.

Esta sequência descreve o comportamento declarado e coberto por testes locais; não foi executada contra AWS.
