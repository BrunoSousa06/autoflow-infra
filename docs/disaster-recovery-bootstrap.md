# Diagnóstico e bootstrap inicial de Disaster Recovery

> Registro histórico de uma implementação experimental posteriormente removida. Os scripts de bootstrap/guard e o coletor de inventário referenciados neste documento não existem neste checkout; os comandos abaixo não são executáveis. Preserve o documento apenas como registro das evidências e limitações observadas; não é um runbook ativo.

## Estado desta entrega

Scripts e testes são locais e somente leitura quando executados nos modos padrão. `bootstrap_state_bucket.py --create` contém o caminho de mutação, mas **não foi executado**. Nenhum bucket, state ou recurso AWS foi criado/alterado. Não há workflow novo nesta entrega. A implementação não autoriza nem executa Terraform.

O inventário fornecido ao guard precisa ser produzido por coleta AWS read-only completa, cobrindo os recursos de todos os roots antes de confirmar `complete: true`. O guard valida consistência e bloqueia dados incompletos; ele não prova por conta própria que o relatório inventariou todas as APIs AWS. Não usar declaração manual incompleta como evidência de reset total. Falta de permissão em qualquer serviço invalida a coleta.

## Pré-requisitos

- Python 3.10+ e AWS CLI v2 disponível no `PATH` (compatível com `ubuntu-latest`). Nenhuma dependência Python externa é necessária.
- Credenciais temporárias AWS válidas providas por ambiente protegido do GitHub (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`); não colocá-las em argumentos, arquivos ou logs.
- Permissão `sts:GetCallerIdentity`; o guard compara a conta efetiva com `--expected-account` e verifica a região do relatório.
- Conta/região e nome do bucket informados por configuration/Environment, não codificados nos scripts. Região default `us-east-1`; usar `AWS_EXPECTED_ACCOUNT_ID`/validação de identidade antes de integrar em workflow.
- Permissões S3 read para `HeadBucket`, `HeadObject`, `GetPublicAccessBlock`, `GetBucketVersioning`, `GetBucketEncryption`. Para criação futura, as permissões de `CreateBucket`, `PutPublicAccessBlock`, `PutBucketVersioning`, `PutEncryptionConfiguration` precisam ser confirmadas no Learner Lab.
- A aprovação da política Academy/IAM e do ambiente GitHub deve anteceder qualquer uso de `--create`. `AccessDenied`, `403`, erro de rede ou erro genérico sempre bloqueiam classificação como ausência.

## Diagnóstico do bucket

Somente leitura:

```bash
python scripts/bootstrap_state_bucket.py --bucket "$AWS_TERRAFORM_STATE_BUCKET" --region "$AWS_REGION" --expected-owner "$AWS_EXPECTED_ACCOUNT_ID"
```

Saídas esperadas em JSON:

- `status=ausente`, código `0`: apenas um 404/NoSuchBucket explícito foi observado; significa que o bucket está ausente, não que recursos AWS ou states locais/remotos estejam todos ausentes.
- `status=presente`, `ready=true`, código `0`: bucket acessível, com bloqueio de acesso público, versionamento e criptografia server-side já habilitados.
- `status=presente`, `ready=false`, código `3`: configuração incompleta; o script não a corrige implicitamente.
- mensagem `Bootstrap de state bloqueado`, código `2`: acesso negado, bucket possivelmente de outro owner, AWS CLI ausente ou erro não conclusivo. Não repetir como tentativa de “ausente”.

Criação futura explicitamente opt-in (não executar sem nova aprovação operacional):

```bash
python scripts/bootstrap_state_bucket.py --bucket "$AWS_TERRAFORM_STATE_BUCKET" --region "$AWS_REGION" --expected-owner "$AWS_EXPECTED_ACCOUNT_ID" --create
```

O modo `--create` não é idempotente em configuração incompleta: falha fechado e não repara bucket existente. Se criar bucket e uma chamada posterior falhar, o resultado pode ser configuração parcial; interromper e revisar manualmente, sem exclusão automática.

## Inspeção das keys e guard de reset

O `recovery_state_guard.py` verifica novamente `HeadBucket`, consulta uma lista explícita de keys informada pelo operador/configuração e combina os resultados com um relatório JSON de inventário AWS read-only. Keys não são hardcoded. Exemplo do formato de relatório, **somente após inventário real completo**:

```json
{
  "complete": true,
  "account_id": "<conta AWS esperada>",
  "region": "us-east-1",
  "checks_complete": true,
  "errors": [],
  "resources": [
    {"id": "eks:eks-autoflow", "status": "present"},
    {"id": "rds:<identificador-configurado>", "status": "absent"}
  ]
}
```

Comando:

```bash
python scripts/recovery_state_guard.py \
  --bucket "$AWS_TERRAFORM_STATE_BUCKET" \
  --region "$AWS_REGION" \
  --expected-account "$AWS_EXPECTED_ACCOUNT_ID" \
  --bucket-status presente \
  --keys "$AWS_TF_STATE_KEY_INFRA,$AWS_TF_STATE_KEY_RDS,$AWS_TF_STATE_KEY_LAMBDA,$AWS_TF_STATE_KEY_APP,$AWS_TF_STATE_KEY_API_GATEWAY" \
  --inventory-json recovery-inventory.json
```

As cinco keys ativas confirmadas pelo operador são `eks/terraform.tfstate`, `rds/terraform.tfstate`, `lambda/terraform.tfstate`, `api-gateway/terraform.tfstate` e `application/autoflow/terraform.tfstate`; Kong legado está excluído. O exemplo de variáveis deve ser preenchido com esses valores de configuração, não com secrets. Não escrever secrets ou conteúdo de state no JSON.

Classificações/resultados:

| Classificação | Exit code | Significado e decisão |
| --- | ---: | --- |
| `bucket-ausente` | `3` | Bootstrap em fase própria e nova inspeção necessária; nenhum state pode ser considerado ausente ainda. |
| `reset-completo-verificado` | `0` | Todas as keys consultadas estão ausentes e o inventário completo não lista recursos sobreviventes. É precondição de diagnóstico, não autorização automática para Terraform. |
| `reset-parcial-com-recursos-sobreviventes` | `3` | State ausente com recurso existente. Apply de state vazio bloqueado; restaurar backup/importar e revisar plan. |
| `reset-parcial` | `3` | Mistura de states existentes/ausentes. Recuperar somente roots ausentes após analisar dependências. |
| `states-presentes` | `3` | Validar lineage/conta/região e plan; não iniciar state novo. |
| `Recuperação bloqueada` | `2` | Inventário incompleto/inconclusivo, AccessDenied, falha de API, bucket mudou ou JSON inválido. Não interpretar como ausência. |

O guard exige que conta/região do relatório correspondam aos argumentos, `checks_complete=true` e `errors=[]`, mas não gera/verifica criptograficamente relatórios. Use a saída de `inventory_recovery.py`, não inventário manual. O guard não chama Terraform e não implementa import/adoption. Mesmo `ready_for_new_state=true` não autoriza Apply: o workflow futuro precisa manter revisão humana real e revalidar inventário e state imediatamente antes do uso.

## Testes e execução futura

```bash
python -m unittest discover -s scripts -p 'test_bootstrap_state_bucket.py' -v
python -m unittest discover -s scripts -p 'test_recovery_state_guard.py' -v
```

Os testes usam mocks e não acessam AWS. Para teste manual, iniciar somente pelos modos read-only. Não executar `--create`, `terraform plan/apply/destroy`, nem aplicar o resultado do guard nesta fase.

## Limitações e próximo trabalho

O documento plano (`docs/specs/aws-academy-disaster-recovery/implementation-plan.md` no workspace compartilhado) estabelece T02 como validação externa de IAM/SCP/quotas/custos e Required reviewers. Em 15/10/2026 o inventário read-only AWS foi executado pelo perfil `fiap-lab`; todos os estados e recursos AWS cobertos foram consultados sem AccessDenied e o relatório marcou `complete=true`. A API de Service Quotas foi legível. Isso não comprova operações de criação, permissões IAM/SCP de worker/runner, custo/crédito, saída HTTPS nem aprovação GitHub. O GitHub CLI não está autenticado e as proteções reais de Environment permanecem desconhecidas.

O inventário encontrou bucket e cinco keys ativos presentes; controls de public-access block, versioning e encryption habilitados; VPC e seis subnets; três route tables, NAT Gateway e Internet Gateway; EKS e node group `ACTIVE`; RDS `available`; Lambda `Active`; API Gateway `autoflow-homolog`; `t3.small` ofertado na região. Nenhuma EC2 Runner identificada pela convenção Name/Component foi encontrada. No endpoint EKS, acesso privado e público estão habilitados, com CIDR público restrito observado (não `0.0.0.0/0`); nenhuma alteração foi feita. Esses estados são fotografia do momento, não garantia de disponibilidade futura.

As consultas `Service Quotas` reportaram limites aplicados consultáveis: quota `Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances` com valor 256 (a resposta retornou Unit `None`), 5 Elastic IPs, EKS 100 clusters/30 node groups por cluster, RDS 40 DB instances, Lambda 1000 concurrent executions e API Gateway 600 Regional APIs. Não foi calculada folga de todas as quotas nem orçamento do Academy; VPC/subnet/NAT e limites de crédito/SCP requerem confirmação própria. `DescribeInstances` passou para o perfil de operador nesta sessão, mas não resolve a negação SCP anteriormente relatada no contexto da role dos worker nodes.

O inventário dos states e roots foi fechado com cinco states ativos e sem Kong: `eks/terraform.tfstate`, `rds/terraform.tfstate`, `lambda/terraform.tfstate`, `api-gateway/terraform.tfstate`, `application/autoflow/terraform.tfstate`. Dependências confirmadas: RDS ← EKS; Lambda ← EKS+RDS; API Gateway ← EKS (com Lambda como data source); aplicação ← RDS (e consulta EKS). Nenhum state foi baixado.

Riscos ainda bloqueiam workflow/Apply: falta autenticação GitHub para ler Required reviewers/Variables; writes IAM e IAM PassRole não foram testados e não podem ser inferidos de Describe; conectividade GitHub/SSM e quota/custo Academy não comprovados; instância sem tag runner exigiria confirmação da convenção de descoberta para um reset integral com EC2 existentes. Não avançar para T03/T04/T06 nesta continuação.

## Inventário read-only e pré-requisitos (T01/T02)

O inventário automatizado está em `scripts/inventory_recovery.py`. Ele consulta metadados via AWS CLI usando perfil local (default `fiap-lab`), nunca obtém o conteúdo dos Terraform States. Uso:

```bash
python scripts/inventory_recovery.py \
  --profile fiap-lab \
  --region "$AWS_REGION" \
  --expected-account "$AWS_EXPECTED_ACCOUNT_ID" \
  --bucket "$AWS_TERRAFORM_STATE_BUCKET" \
  --output C:/caminho-local-protegido/recovery-inventory.json
```

Saída exit `0` significa que todas as consultas definidas foram completadas, **não** que os recursos estão ausentes nem que permissões de criação foram concedidas. Exit `2` significa uma ou mais consultas inconclusivas; o relatório inclui apenas nome da checagem e categoria (`access_denied`, `query_failed`, `invalid_response` etc.), sem imprimir stderr AWS. Nenhuma consulta `Create`, `Put`, `Update`, `Delete`, `RunInstances` ou operação Terraform é chamada.

O inventário inclui o bucket e `HeadObject` para estas cinco keys ativas; não inclui Kong legado:

| Root | Key ativa | Dependências observadas no código/workflows locais |
| --- | --- | --- |
| `autoflow-infra/infra` | `eks/terraform.tfstate` | Root base sem `terraform_remote_state`; cria VPC/subnets/EKS/node group. |
| `autoflow-db/infra` | `rds/terraform.tfstate` | Lê EKS (`eks/terraform.tfstate`) para VPC/subnets. |
| `autoflow-lambda/infra` | `lambda/terraform.tfstate` | Lê EKS e RDS. Nome de função por default `autoflow-cpf-validator-homolog`; Lambda Terraform deste checkout não declara API Gateway. |
| `autoflow-infra/infra/api-gateway` | `api-gateway/terraform.tfstate` | Lê EKS; consulta EKS/node group e Lambda por data sources. API configurada por default como `autoflow-homolog`. |
| `autoflow/infra` | `application/autoflow/terraform.tfstate` | Lê RDS via remote state e consulta EKS diretamente. O deployment atual está bloqueado no workflow devido à falta de rota privada do runner GitHub-hosted. |

As keys da tabela foram fornecidas pelo operador e reconciliadas com o mapeamento de backend/remote state observado nos workflows, Terraform e documentação das raízes. As variáveis de GitHub ainda não foram consultadas: o `gh` local não está autenticado. Os roots em `autoflow-infra/infra/api-gateway` e `autoflow-infra/infra` têm workflows e keys separados.

Alvos consultados pela coleta: VPC identificada pela tag `Name=main-vpc` (conforme `infra/vpc.tf`); subnets com tag de cluster EKS no VPC identificado (IDs são descobertos em runtime); cluster/node group por nome; RDS por identifier; Lambda por function name; HTTP API Gateway por nome; EC2 runner pela tag Name contendo `runner` ou `Component=github-runner`; bucket/keys por configuração; disponibilidade regional `t3.small`; quotas legíveis dos serviços EC2, EKS, RDS, Lambda e API Gateway.

**Importante:** runner só é identificado com convenção tagueada. Instâncias EC2 sem tag Name tornam a cobertura do runner inconclusiva; não classificar reset total. A configuração proposta `autoflow-github-runner` pode ser substituída pelo parâmetro `--runner-name`, mas o projeto ainda não tem recurso runner implementado. Consultas de quotas listam limites legíveis, mas não calculam todo o uso/folga de todas as cotas nem custos. Instance type `t3.small` oferecido na região não comprova quota, crédito ou autorização para `RunInstances`.

### Permissões e validações com evidência

As chamadas read-only que passam demonstram somente o acesso à respectiva operação de leitura na sessão testada. `HeadObject` não valida `GetObject`; `Describe*`/`Get*` não validam `Create*`, `Put*`, `RunInstances`, `iam:PassRole` ou updates. Permissões de escrita estão deliberadamente reportadas como `not_tested_no_mutation` no JSON.

| Finalidade futura | Permissões candidatas a validar com administrador Academy |
| --- | --- |
| Inventário | `sts:GetCallerIdentity`; `s3:ListBucket` (HeadBucket), `s3:GetObject` (HeadObject metadata), `s3:GetBucketVersioning`, `s3:GetEncryptionConfiguration`, `s3:GetBucketPublicAccessBlock`; `ec2:DescribeVpcs`, `DescribeSubnets`, `DescribeRouteTables`, `DescribeNatGateways`, `DescribeInternetGateways`, `DescribeSecurityGroups`, `DescribeInstances`, `DescribeInstanceTypeOfferings`; `autoscaling:DescribeAutoScalingGroups`; `eks:DescribeCluster`, `DescribeNodegroup`; `rds:DescribeDBInstances`; `lambda:GetFunction`; `apigateway:GET`; `servicequotas:ListServiceQuotas`. |
| Backend Terraform remoto/lock | `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`; para S3 lockfile, `GetObject`, `PutObject`, `DeleteObject` na key `.tflock`; se SSE-KMS, `kms:Encrypt`, `kms:Decrypt`, `kms:GenerateDataKey`. Nesta coleta não se leu state nem lockfile para evitar baixar state sensível. |
| Bootstrap S3 futuro | `s3:CreateBucket`, `s3:PutPublicAccessBlock`, `s3:PutBucketVersioning`, `s3:PutEncryptionConfiguration`; nenhum foi testado/executado. |
| Terraform Apply por serviço | Writes próprios de `ec2:CreateVpc`, `CreateSubnet`, `CreateRoute`, `CreateInternetGateway`, `CreateNatGateway`, `CreateSecurityGroup` e regras associadas; EKS, RDS, Lambda, API Gateway/ELB/CloudWatch; mais `iam:PassRole` para roles já aprovadas. As permissões exatas dependem dos plans/roles; SCP explicit deny não é superado por Allow IAM. |
| EC2 Runner | `ec2:RunInstances`, `ec2:CreateTags`, `ec2:CreateNetworkInterface`, `ec2:CreateSecurityGroup` e regras de saída em SG dedicado, `iam:PassRole` e instance profile/role previamente aprovada. Criar role/profile/SG ou alterar regras exige permissões que não foram testadas e pode ser vedado pelo Academy. |
| Inspeção IAM | Consultar roles preexistentes exige `iam:GetRole`, `iam:ListAttachedRolePolicies` e `iam:GetRolePolicy` para os ARNs aprovados. Não foi feito porque roles efetivas não estavam disponíveis nas vars consultadas (GitHub CLI sem sessão). `iam:SimulatePrincipalPolicy` pode auxiliar análise, mas não comprova SCP, quotas nem autorização operacional real de Create no Learner Lab. |
| GitHub Actions | Credenciais temporárias com session token em Environment protegido; acesso a vars/secrets necessários; workflow permission mínima. Required reviewers reais requerem leitura autenticada da configuração de Environment (`administration:read` conforme API/plano GitHub). GitHub CLI atual não está autenticado; reviewers não foram verificados. |

Quotas da API `Service Quotas` acessíveis nesta sessão não são certificação de folga: comparar valores com uso atual e limite de duração/créditos do Academy em validação específica. Conectividade de saída HTTPS/SSM/GitHub e acesso ao EKS privado também não foram comprovados por API de inventário. O `ec2:DescribeInstances` atual foi acessível ao perfil `fiap-lab`, mas isso não invalida o relato de SCP deny no contexto IAM dos worker nodes durante bootstrap.
