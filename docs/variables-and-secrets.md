# Variables e secrets

Inventário observado nos workflows e Terraform deste repositório. Os workflows selecionam o Environment `homolog` em `develop` e `production` em `main`; Apply exige dispatch manual e a proteção do Environment. A configuração efetiva de Environments/reviewers não foi consultada e não há produção declarada como provisionada. New Relic é consumido apenas por `newrelic.yml`. CI de PR não requer acesso AWS.

## GitHub Actions — Secrets

| Nome | Tipo / finalidade | Onde configurar; origem | CI / CD | Exemplo seguro | Consumidor; default/ausência |
|---|---|---|---|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | Secrets; sessão temporária AWS | Repository Secrets; mesma sessão AWS Academy Learner Lab | CD | Não aplicável | `.github/workflows/pipeline.yml`, `api-gateway.yml`; usados pelos jobs de Plan e Apply, sem defaults. |
| `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE` | Secret para cifrar o Plan Terraform entre os jobs Plan/Apply | Environment Secrets `homolog` e `production`; mesmo valor nos jobs do mesmo Environment | Plan/Apply | Não aplicável | `pipeline.yml` e `newrelic.yml`; obrigatório, sem default. Não registrar em logs nem artifacts em texto claro. |
| `AUTOFLOW_READ_TOKEN` | Secret opcional para checkout do contrato `autoflow` | GitHub Repository secret; token de leitura se o repo for privado | CI de gateway | Não aplicável | `api-gateway.yml`; fallback `${{ github.token }}`. Se token padrão tiver acesso, não cadastrar. |
| `GITHUB_TOKEN` (`github.token`) | Token automático de checkout pelo workflow | Gerado pelo GitHub; não cadastrar | CI | Não aplicável | `api-gateway.yml`; default para checkout do contrato. |
| `NEW_RELIC_API_KEY` | User API key do provider New Relic; diferente da License Key de ingestão | GitHub Secret separado por Environment | Inventário remoto e Terraform New Relic Plan/Apply | Não aplicável | `newrelic.yml` → `TF_VAR_newrelic_api_key`; variável de ambiente sensível, ausente de argumentos/logs. Necessária ao inventário remoto antes de criar recursos. |

## GitHub Actions — Variables

| Nome | Finalidade | Onde; origem | CI / CD | Exemplo seguro | Consumidor; default/ausência |
|---|---|---|---|---|---|
| `AWS_REGION` | Região AWS | Repository Variable | CD | `us-east-1` | Ambos workflows de deploy; obrigatória, sem default. |
| `AWS_EXPECTED_ACCOUNT_ID` | Conta permitida pelos guards | Repository Variable | CD | `123456789012` | Ambos; obrigatória, sem default. |
| `AWS_TERRAFORM_STATE_BUCKET` | Bucket S3 compartilhado pelos roots Terraform | Repository Variable, quando configurada | CD | Nome derivado do account ID e região | Bootstrap prioriza este valor; quando ausente, usa `autoflow-tfstate-learnerlab-<AWS_EXPECTED_ACCOUNT_ID>-<AWS_REGION>`. |
| `AWS_TF_STATE_KEY_INFRA` | Key state VPC/EKS | Repository Variable | CD | `homolog/infra/terraform.tfstate` | `pipeline.yml` e input state remoto em `api-gateway.yml`; obrigatória. |
| `AWS_TF_STATE_KEY_NEWRELIC` | Key exclusiva de state New Relic no bucket já utilizado | Environment Variable em `homolog` e `production` | Plan/Apply New Relic | `homolog/newrelic/terraform.tfstate` | `newrelic.yml`; necessária em cada Environment, sem default. Use keys distintas por Environment. |
| `AWS_TF_STATE_KEY_GATEWAY` | Key exclusiva do state API Gateway | Repository Variable | CD | `homolog/api-gateway/terraform.tfstate` | `api-gateway.yml`; obrigatória, sem default. |
| `API_GATEWAY_CORS_ORIGINS` | Lista JSON de origens HTTPS CORS | Repository Variable | CD | `[]` | `api-gateway.yml`; obrigatória no shell preflight, sem default; array JSON. |
| `AUTOFLOW_REPOSITORY` | Repositório de contrato verificado pelo CI | GitHub Repository Variable | CI, opcional | `organizacao/autoflow` | `api-gateway.yml`; default `${{ format('{0}/autoflow', github.repository_owner) }}`. |
| `AUTOFLOW_CONTRACT_REF` | Ref de contrato | GitHub Repository Variable | CI, opcional | `develop` | `api-gateway.yml`; default `develop`. |
| `TERRAFORM_APPLY_APPROVAL_CONFIGURED` | Guard adicional de Apply | Repository Variable; marcar `true` somente após configurar Required reviewers nos Environments usados | CD se `apply/deploy=true` | `true` | Workflows de deploy; ausente/diferente bloqueia Apply. Não substitui proteção real do Environment. |
| `ENABLE_NEWRELIC_KUBERNETES`, `ENABLE_NEWRELIC_ACCOUNT_RESOURCES` | Ativam separadamente a integração Kubernetes e os recursos da conta | GitHub Variables opcionais de cada Environment | `newrelic.yml` Plan/Apply | `false` | O workflow usa `false` se ausentes. Para habilitar, configurar `true` após aprovação; não são inputs de dispatch. Exclusão requer dispatch Apply com `allow_destructive=true` e Required reviewers. |
| `NEW_RELIC_ACCOUNT_ID`, `NEW_RELIC_REGION`, `NEW_RELIC_API_KEY` | Account ID, região New Relic e User API key do provider/inventário remoto | Variables e Secret separados por Environment | Inventário e Plan/Apply New Relic | Não aplicável | Região e API key são obrigatórias para confirmar o inventário remoto em todo Plan; Account ID é obrigatório quando `ENABLE_NEWRELIC_ACCOUNT_RESOURCES=true`. A API key não é a License Key de ingestão. |
| `NEW_RELIC_SYNTHETIC_URL`, `NEW_RELIC_SYNTHETIC_LOCATIONS_JSON` | Endpoint e locations do Synthetic | Variables opcionais do Environment | Plan/Apply de recursos de conta | URL vazia e `[]` | Devem ser fornecidas juntas; ausentes deixam monitor desabilitado. |
| `NEW_RELIC_API_GATEWAY_DASHBOARD_QUERIES_JSON` | Lista JSON com títulos e NRQL de métricas AWS API Gateway já observadas | GitHub Variable de cada Environment alvo | Plan/Apply | Lista vazia | Opcional; queries validadas são consumidas pela página do dashboard. Não provisiona integração AWS↔New Relic nem altera o API Gateway. |

`NEW_RELIC_API_KEY` é Secret; os demais inputs desta tabela são Variables não sensíveis. `newrelic_environment` é derivado do Environment GitHub já selecionado (`homolog`/`production`). `api-gateway.yml` e `newrelic.yml` descobrem o cluster e o node group por consultas EKS após validar a conta/região e exigem um único resultado; não cadastrar `EKS_CLUSTER_NAME` nem `EKS_NODEGROUP_NAME`. O pipeline da plataforma conhece o nome derivado de `eks-${project_name}` (default Terraform `eks-autoflow`). O State publica os nomes e as roles efetivas do cluster e dos nodes em outputs separados. Os demais secrets/variables AWS existentes continuam necessários conforme tabela.

## Terraform inputs

### Root plataforma (`infra/vars.tf`)

| Input | Obrigatoriedade/default | Finalidade; workflow/origem |
|---|---|---|
| `project_name` | Opcional; `autoflow` | Prefixo dos recursos. |
| `region_default` | Opcional; `us-east-1` | Região; workflow mapeia `AWS_REGION`. |
| `aws_profile` | Opcional; `null` | Perfil AWS local. |
| `aws_allowed_account_ids` | Obrigatório; sem default, lista não vazia de IDs de 12 dígitos | Guard do provider; `AWS_EXPECTED_ACCOUNT_ID` convertido em lista pelo workflow. |
| `cidr_vpc` | Opcional; `10.0.0.0/16` | Endereçamento VPC. |
| `cluster_role_arn`, `node_role_arn`, `operator_access_role_arn` | Obrigatórios, sem default | `pipeline.yml` descobre as roles de cluster e nodes por STS/IAM; localmente, forneça os `TF_VAR_*` após executar o preflight de descoberta. A role operador é derivada da sessão STS. O Apply valida as roles embutidas no Plan aprovado, sem redescobri-las. |
| `instance_type` | Opcional; `t3.medium` | Tipo de instância node. |
| `node_min_size`, `node_desired_size`, `node_max_size` | Opcionais; `2`, `2`, `3` | Tamanho node group. |
| `cluster_endpoint_private_access`, `cluster_endpoint_public_access` | Opcionais; `true`, `true` | Acesso endpoint EKS. |
| `cluster_endpoint_public_access_cidrs` | Opcional; default `189.6.8.245/32`; validação exige CIDR se endpoint público habilitado | CIDR permanente inicial do endpoint. Terraform ignora drift nesse atributo; o workflow gerencia o `/32` temporário do runner e preserva os CIDRs preexistentes ao limpar o lease. |
| `create_nat_gateway`, `create_operator_access_entry` | Opcionais; `true`, `true` | Controlam criação de recursos. |

Para descoberta local no PowerShell, configure primeiro `AWS_PROFILE`, `AWS_REGION` e `AWS_EXPECTED_ACCOUNT_ID` e execute no root do repositório:

```powershell
$rolesJson = python scripts/verify_eks_iam_roles.py --discover --cluster eks-autoflow --region $env:AWS_REGION --expected-account $env:AWS_EXPECTED_ACCOUNT_ID
$roles = $rolesJson | ConvertFrom-Json
$env:TF_VAR_cluster_role_arn = $roles.cluster_role_arn
$env:TF_VAR_node_role_arn = $roles.node_role_arn
```

O comando falha se a conta STS divergir, se a trust policy ou policies obrigatórias não corresponderem, se o cluster ativo usar outra Cluster Role, ou se não houver exatamente uma role candidata de cada tipo. O Terraform Apply deve usar o arquivo de Plan salvo, que contém os ARNs aprovados.

### Root New Relic (`infra/newrelic/providers.tf`)

| Input | Obrigatoriedade/default | Finalidade; workflow/origem |
|---|---|---|
| `aws_region`, `aws_allowed_account_ids`, `eks_cluster_name` | Fornecidos pelo workflow | Região/conta AWS e EKS consultado; AWS Variables existentes. |
| `enable_newrelic_kubernetes`, `enable_newrelic_account_resources` | Opcionais; `false` | Flags de integração Kubernetes e recursos de conta em `newrelic.yml`. |
| `newrelic_account_id`, `newrelic_region`, `newrelic_api_key` | Nulos localmente; key sensível | Provider New Relic e inventário remoto; Environment Variables/Secret. |
| `newrelic_environment`, `newrelic_namespace`, `newrelic_license_secret_name`, `newrelic_license_secret_key` | `local`, `default`, `newrelic-license`, `licenseKey` | Identificadores técnicos do ambiente, cluster e Secret referenciado; nenhum valor de License Key fica no Terraform. |
| `newrelic_synthetic_url`, `newrelic_synthetic_locations` | `""`, `[]` | Configuração opcional de Synthetic no Environment. |
| Consultas de disponibilidade, uso e API Gateway | String vazia/lista vazia | Opcional; NRQL só é habilitada após confirmação dos atributos/eventos. |

### Root API Gateway (`infra/api-gateway/variables.tf`)

| Input | Obrigatoriedade/default | Finalidade; workflow/origem |
|---|---|---|
| `aws_region` | `us-east-1` | Região; `AWS_REGION`. |
| `expected_account_id` | Obrigatório; sem default; 12 dígitos | Conta; `AWS_EXPECTED_ACCOUNT_ID`. |
| `environment` | `homolog` | Nome do ambiente. |
| `terraform_state_bucket` | Obrigatório; sem default | Bucket externo; `AWS_TERRAFORM_STATE_BUCKET`. |
| `infra_state_key` | `eks/terraform.tfstate` | State plataforma; `AWS_TF_STATE_KEY_INFRA`. |
| `cluster_name`, `nodegroup_name` | Valores obtidos por consultas EKS no workflow | O pipeline exige exatamente um cluster e um node group, valida estado `ACTIVE` e passa os nomes descobertos ao Terraform. |
| `lambda_function_name` | Descoberto no preflight | Workflow confirma a Lambda `autoflow-cpf-validator-homolog` via AWS e injeta o nome. |
| `cors_origins` | `[]` | Origens CORS; `API_GATEWAY_CORS_ORIGINS`. |
| `alarm_actions` | `[]` | ARNs SNS opcionais; vazio não configura notificações. Workflow atual não injeta esta variável. |

## Referências indiretas

`api-gateway.yml` verifica checkout do repositório `autoflow` (padrão ref `develop`), controllers/allowlist, cluster e node group `ACTIVE`, além de State remoto. Cluster/node group são consultados no EKS e a Lambda `autoflow-cpf-validator-homolog` é confirmada via AWS; não cadastrar `EKS_CLUSTER_NAME`, `EKS_NODEGROUP_NAME` nem `AWS_LAMBDA_FUNCTION_NAME`. `scripts/review_gateway_plan.py` consome `TF_VAR_expected_account_id`. Os GitHub `AWS_*` são mapeados para Terraform inputs `aws_*`; não são todos nomes idênticos. Produção não é ambiente implementado aqui.

**Fontes:** `.github/workflows/pipeline.yml`, `.github/workflows/api-gateway.yml`, `infra/vars.tf`, `infra/api-gateway/variables.tf`, scripts de validação e `README.md`.
