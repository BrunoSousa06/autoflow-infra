# Primeiro provisionamento do EKS após reset

O workflow `Pipeline` verifica a existência do cluster EKS antes de preparar o Plan. Se o cluster não existir, apenas naquele Plan a variável `enable_newrelic_kubernetes` é sobrescrita para `false`; os recursos de VPC, EKS e node group continuam no mesmo Terraform root e no mesmo Plan aprovado. Os data sources EKS e a configuração conectável do provider Helm também ficam inativos nessa fase. Não há `-target` nem aplicação de um Plan diferente do artifact aprovado.

## Sequência após reset do Learner Lab

1. Confirme/reabra o Learner Lab e execute o workflow `Pipeline` em `develop` (push) ou via `workflow_dispatch` com `apply` habilitado. O Plan identifica o EKS ausente e o Apply aprovado cria/reconcilia VPC, cluster e node group sem consultar Kubernetes nem instalar Helm. Em `main`, use `workflow_dispatch`; a aprovação do Environment `production` continua obrigatória.
2. Aguarde o Apply terminar e o node group ficar operacional. Execute o pipeline existente do repositório `autoflow` na branch/environment correspondente. Ele prepara kubeconfig e sincroniza automaticamente a License Key existente do GitHub Secret para AWS Secrets Manager e para o Secret Kubernetes; em caso de falha, esse pipeline para sem aplicar a aplicação.
3. Execute novamente o workflow `Pipeline` de `autoflow-infra` (em `develop`, `workflow_dispatch` com `apply` habilitado). Agora o EKS é detectado, o Plan inclui `nri-bundle` quando `ENABLE_NEWRELIC_KUBERNETES=true` e o Apply exige a verificação do Secret `newrelic-license`/`licenseKey` antes de executar o artifact aprovado.

Se o cluster existir, mas o Secret/License Key estiver ausente, vazio ou ilegível, a etapa de validação falha e bloqueia o Apply. Falhas AWS diferentes de `ResourceNotFoundException` também bloqueiam a classificação de cluster ausente. O Plan criptografado, checksums, GPG, lockfile readonly, proteção contra destruição e Required reviewers seguem no fluxo existente.

Se o state ainda registrar o antigo `helm_release` removido pelo reset, o Plan poderá mostrar a remoção dessa referência órfã. O guard destrutivo geral continua ativo: em `workflow_dispatch`, revise o Plan e marque `allow_destructive` somente se as exclusões/substituições estiverem aprovadas; caso contrário, o Apply permanece bloqueado.

## Passos manuais

- Reativar o Learner Lab e garantir que as GitHub Actions Variables/Secrets, AWS credentials temporárias e Required reviewers dos Environments estejam válidos.
- Disparar os workflows em sequência conforme acima; não disparar o deploy de `autoflow` antes do primeiro Apply de infraestrutura.
- Se a License Key existente diferir entre GitHub Secrets e AWS Secrets Manager, interromper e fazer a rotação controlada indicada pelo pipeline `autoflow`; não criar uma segunda key/variável.

Esta sequência descreve o comportamento declarado e coberto por testes locais; não foi executada contra AWS.
