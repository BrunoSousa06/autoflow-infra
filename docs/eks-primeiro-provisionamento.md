# Primeiro provisionamento do EKS após reset

O workflow `Pipeline` e o root `infra/` gerenciam somente VPC, rede, EKS e node group. New Relic não é planejado nem aplicado neste root; seu root é independente em `infra/newrelic/`. Esta sequência descreve os workflows e configurações versionados, não comprova implantação nem validação atual na AWS.

## Preparação dos Environments e States

1. Confirme/reative o AWS Academy Learner Lab. Configure os GitHub Environments `homolog` e `production` com conta esperada, região, bucket, State Keys e credenciais temporárias próprias do Environment. Audite Required reviewers e branch policies com uma identidade administrativa autorizada antes de definir `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true` em cada Environment.
2. Valide a matriz externa dos seis Terraform roots (`vpc_eks`, `rds`, `lambda`, `application`, `api_gateway` e `newrelic`) com `python scripts/terraform_state_contract.py <caminho-externo-para-configuracao.json>`. Use uma key distinta por root e Environment e confirme as relações de State dos consumidores. O validador é local e não prova que os States existam na AWS. As Variables e limitações por root estão em [arquitetura — States e ownership](api-gateway/arquitetura.md#states-e-ownership).
3. Execute o [bootstrap isolado do bucket Terraform State](state-bucket-bootstrap.md) em `develop` para `homolog` ou `main` para `production`. Use somente `approve_state_bucket_creation=true`; mantenha `apply`, `approve_eks_state_reconciliation` e `allow_destructive` em `false`. O job verifica os valores obrigatórios e a conta STS, e não inicia Plan, Apply ou Terraform init. A aprovação nativa do Environment continua obrigatória; a configuração de Required reviewers deve ter sido auditada externamente.

## Sequência de provisionamento

1. Depois do bootstrap bem-sucedido, faça um dispatch separado do workflow `Pipeline` com `approve_state_bucket_creation=false` e `apply=false` para inspecionar o Plan VPC/EKS. O Plan verifica novamente identidade e conformidade do bucket, valida as Cluster/Node Roles, verifica State e fingerprint, e publica artifact criptografado para revisão. Confirme os recursos e roles declarados; divergências bloqueiam o fluxo.
2. Após revisar o Plan, faça outro dispatch do `Pipeline` com `approve_state_bucket_creation=false` e `apply=true`. Esse run gera um Plan novo e aplica o mesmo artifact após os checks e a aprovação do Environment. Em `main`, a branch também precisa estar protegida e o Environment `production` deve ter Required reviewers efetivos. `allow_destructive` permanece `false` salvo autorização operacional separada após revisão específica.
3. Execute os pipelines RDS e Lambda nessa ordem; Lambda consome os States EKS e RDS. Confirme no repositório e Environment correspondentes que as State Keys não colidem nem cruzam ambientes antes de qualquer init.
4. Execute `Migração HTTP API` em `autoflow-infra/develop` ou no Environment de produção configurado. Exige EKS/node group ativos e Lambda existente; pode criar VPC Link e ALB antes dos workloads da aplicação. O workflow não cria o bucket S3.
5. Execute o pipeline de `autoflow` no Environment correto. Ele exige RDS e API Gateway, descobre endpoint/cluster e sincroniza a License Key existente para Secrets Manager e Secret Kubernetes; em caso de falha, para sem aplicar a aplicação.
6. Execute `New Relic Pipeline` por `workflow_dispatch` depois que a aplicação e seus Secrets estiverem prontos. O workflow opera somente no root `infra/newrelic/`, valida conta/região, EKS/node groups, Deployments e Services; com Kubernetes New Relic habilitado, também valida o Secret `newrelic-license`/`licenseKey`. O bucket já deve existir e estar conforme; não é necessário reaplicar VPC/EKS.

Se Deployments/Services não estiverem prontos, ou se o Secret/License Key exigido estiver ausente, vazio ou ilegível, a validação falha e bloqueia o Apply New Relic. Falhas AWS e inventário remoto ambíguo também bloqueiam a operação. Plan criptografado, checksums, GPG, lockfile readonly, fingerprint, guard destrutivo e Required reviewers são proteções independentes por workflow/root.

No cenário A, confirme que os objetos New Relic e os endereços em ambos os States estão ausentes; não há migração. No cenário B, o workflow New Relic bloqueia recursos ainda registrados no root legado e não remove/importa State. Siga o [runbook de migração de State](newrelic-state-migration.md) com autorização explícita. O workflow principal também bloqueia Plans que tentem destruir recursos New Relic residuais.

## Recuperação e limites

- Se o bootstrap falhar por conta, ownership ou controle incompatível, não execute Plan/Apply. Siga a recuperação no [runbook do bucket](state-bucket-bootstrap.md); nenhuma correção ou exclusão automática deve ser tentada.
- Se Deployments/Services não estiverem prontos ou as credenciais forem inválidas, interrompa e corrija a configuração no Environment/repositório responsável antes de um novo dispatch.
- Se a License Key existente diferir entre GitHub Secrets e AWS Secrets Manager, interrompa e faça a rotação controlada indicada pelo pipeline `autoflow`; não crie uma segunda key/variable.
- Produção dos seis roots, configuração real dos Environments e presença dos recursos AWS não são certificadas por este procedimento. O fluxo de promoção fora de `autoflow-infra` depende dos workflows e State Keys dos respectivos repositórios.
