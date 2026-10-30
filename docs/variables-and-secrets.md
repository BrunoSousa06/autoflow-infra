# Variables e secrets

Inventário observado nos workflows e Terraform deste repositório. `develop` seleciona o Environment `homolog`; `main`, `production`. Os nomes dos recursos EKS são derivados do ambiente. Apply exige configuração completa e proteção efetiva do Environment. O primeiro Apply de API Gateway e New Relic é dispatch explícito depois das dependências; após existir state, mudanças correspondentes em `main` seguem CD automático. CI de PR não requer acesso AWS.

No workflow `Pipeline`, `workflow_dispatch` com `approve_state_bucket_creation=true` executa somente o job isolado de bootstrap do bucket: `validate`, Plan e Apply são ignorados. O job é limitado a `develop`/`homolog` e `main`/`production`, está associado ao Environment selecionado, valida valores não vazios diretamente de `vars`/`secrets` e aguarda a proteção nativa do GitHub. Required reviewers efetivos são auditados externamente por identidade administrativa autorizada antes de habilitar o marcador adicional. Consulte o [procedimento de bootstrap do bucket](state-bucket-bootstrap.md) e a [auditoria externa](github-runner.md#auditoria-administrativa-externa).

Os três nomes não são intercambiáveis: `approve_state_bucket_creation` é o input booleano temporário que autoriza o job independente; `APPROVE_CREATE` era uma Environment Variable do fluxo antigo dentro do Plan e não é lida pelo workflow atual; `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true` é um marcador de configuração adicional, habilitado somente depois da auditoria administrativa dos Required reviewers e políticas de branch. Ele não substitui a proteção nem a aprovação nativa do Environment. Durante o bootstrap, mantenha `apply`, `approve_eks_state_reconciliation` e `allow_destructive` em `false`.

## GitHub Actions — Secrets

| Nome | Tipo / finalidade | Onde configurar; origem | CI / CD | Exemplo seguro | Consumidor; default/ausência |
|---|---|---|---|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | Secrets; sessão temporária AWS | Environment Secrets `homolog` e `production`; os três devem pertencer à mesma sessão Learner Lab | CD | Não aplicável | Jobs de Plan, Apply e bootstrap nos workflows de infraestrutura. Os valores são verificados antes da configuração das credenciais AWS e a identidade STS deve corresponder a `AWS_EXPECTED_ACCOUNT_ID`. Não usar credenciais de uma conta com `AWS_EXPECTED_ACCOUNT_ID` de outra. |
| `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE` | Secret para cifrar o Plan Terraform entre os jobs Plan/Apply | Environment Secrets `homolog` e `production`; mesmo valor nos jobs do mesmo Environment | Plan/Apply | Não aplicável | `pipeline.yml` e `newrelic.yml`; obrigatório, sem default. Não registrar em logs nem artifacts em texto claro. |
| `AUTOFLOW_READ_TOKEN` | Secret opcional para checkout do contrato `autoflow` | GitHub Repository secret; token de leitura se o repo for privado | CI de gateway | Não aplicável | `api-gateway.yml`; fallback `${{ github.token }}`. Se token padrão tiver acesso, não cadastrar. |
| `GITHUB_TOKEN` (`github.token`) | Token automático de checkout pelo workflow | Gerado pelo GitHub; não cadastrar | CI | Não aplicável | `api-gateway.yml`; default para checkout do contrato. |
| `NEW_RELIC_API_KEY` | User API key do provider New Relic; diferente da License Key de ingestão | GitHub Secret separado por Environment | Inventário remoto e Terraform New Relic Plan/Apply | Não aplicável | `newrelic.yml` → `TF_VAR_newrelic_api_key`; variável de ambiente sensível, ausente de argumentos/logs. Necessária ao inventário remoto antes de criar recursos. |

## GitHub Actions — Variables

| Nome | Finalidade | Onde; origem | CI / CD | Exemplo seguro | Consumidor; default/ausência |
|---|---|---|---|---|---|
| `AWS_REGION` | Região AWS | Environment Variable em `homolog` e `production` | CD | `us-east-1` | Obrigatória; o job de bootstrap valida a configuração antes do acesso AWS. |
| `AWS_EXPECTED_ACCOUNT_ID` | Conta AWS autorizada | Environment Variable em cada Environment; ID decimal com 12 dígitos | CD | Não aplicável | Obrigatória; o bootstrap compara a identidade STS antes de qualquer escrita e exige que o proprietário do bucket corresponda a esta conta. |
| `AWS_TERRAFORM_STATE_BUCKET` | Bucket S3 para os roots Terraform daquele ambiente | Environment Variable em cada Environment | CD | Nome do bucket da conta selecionada | Obrigatória e sem derivação automática. O bootstrap valida proprietário, bloqueio de acesso público, versionamento e criptografia; bucket existente incompatível não é alterado automaticamente. |
| `AWS_TF_STATE_KEY_INFRA` | Key do State VPC/EKS | Environment Variable em `homolog` e `production` | CD | Prefixo do Environment e sufixo definido externamente | `pipeline.yml` e consumidores Gateway/New Relic; obrigatória, sem default, e prefixada pelo ambiente selecionado. |
| `AWS_TF_STATE_KEY_NEWRELIC` | Key exclusiva do State New Relic | Environment Variable em `homolog` e `production` | Plan/Apply New Relic | Prefixo do Environment e sufixo definido externamente | `newrelic.yml`; obrigatória, sem default, prefixada pelo ambiente e distinta das demais keys. |
| `AWS_TF_STATE_KEY_GATEWAY` | Key exclusiva do State API Gateway | Environment Variable em `homolog` e `production` | CD | Prefixo do Environment e sufixo definido externamente | `api-gateway.yml`; obrigatória, sem default, e prefixada pelo ambiente selecionado. |
| `API_GATEWAY_CORS_ORIGINS` | Lista JSON de origens HTTPS CORS | Environment Variable em cada Environment | CD | `[]` | `api-gateway.yml`; obrigatória; deve conter um array JSON válido. |
| `AUTOFLOW_REPOSITORY` | Repositório de contrato verificado pelo CI | GitHub Repository Variable | CI, opcional | `organizacao/autoflow` | `api-gateway.yml`; default `${{ format('{0}/autoflow', github.repository_owner) }}`. |
| `AUTOFLOW_CONTRACT_REF` | Ref de contrato | GitHub Repository Variable | CI, opcional | `develop` | `api-gateway.yml`; default `develop`. |
| `TERRAFORM_APPLY_APPROVAL_CONFIGURED` | Guard adicional para ações protegidas | Environment Variable; definir `true` somente depois da auditoria externa de Required reviewers e branch policy no mesmo Environment | Plan/Apply e bootstrap | `true` | Ausente/diferente bloqueia o acesso AWS. É um gate independente; a proteção nativa do Environment continua responsável pelos Required reviewers e pela aprovação. A pipeline não consulta a API administrativa de Environments. |
| `ALLOW_EKS_STATE_RECONCILIATION` | Permite reconciliação delimitada de state/acesso EKS | Environment Variable, padrão ausente/`false` | Plan/Apply VPC/EKS | `false` | `pipeline.yml`; em produção, exige dispatch e input explícito. |
| `ENABLE_NEWRELIC_KUBERNETES`, `ENABLE_NEWRELIC_ACCOUNT_RESOURCES` | Ativam separadamente a integração Kubernetes e os recursos da conta | Environment Variables opcionais | `newrelic.yml` Plan/Apply | `false` | Ausentes usam `false`. Para habilitar, configure `true` no Environment correto; não são inputs de dispatch. Exclusão requer dispatch Apply com `allow_destructive=true` e Required reviewers. |
| `NEW_RELIC_ACCOUNT_ID`, `NEW_RELIC_REGION`, `NEW_RELIC_API_KEY` | Account ID, região New Relic e User API key do provider/inventário remoto | Variables e Secret separados por Environment | Inventário e Plan/Apply New Relic | Não aplicável | Região e API key são obrigatórias para confirmar o inventário remoto em todo Plan; Account ID é obrigatório quando `ENABLE_NEWRELIC_ACCOUNT_RESOURCES=true`. A API key não é a License Key de ingestão. |
| `NEW_RELIC_SYNTHETIC_URL`, `NEW_RELIC_SYNTHETIC_LOCATIONS_JSON` | Endpoint e locations do Synthetic | Environment Variables opcionais | Plan/Apply de recursos de conta | URL vazia e `[]` | Devem ser fornecidas juntas; ausentes deixam monitor desabilitado. |
| `NEW_RELIC_API_GATEWAY_DASHBOARD_QUERIES_JSON` | Lista JSON com títulos e NRQL de métricas AWS API Gateway já observadas | Environment Variable em cada Environment alvo | Plan/Apply | Lista vazia | Opcional; queries validadas são consumidas pela página do dashboard. Não provisiona integração AWS↔New Relic nem altera o API Gateway. |

`NEW_RELIC_API_KEY` é Secret; os demais inputs desta tabela são Variables não sensíveis. `newrelic_environment` deriva do Environment GitHub (`homolog`/`production`). `pipeline.yml` define `project_name=autoflow` em homologação e `autoflow-production` em produção; os nomes de cluster e node group são `eks-<project_name>` e `nodeg-<project_name>`. API Gateway e New Relic consultam diretamente o cluster esperado do ambiente, sem selecionar o único cluster da conta. A Lambda e o API Gateway também recebem o ambiente selecionado. Não cadastrar `EKS_CLUSTER_NAME` nem `EKS_NODEGROUP_NAME`.

## Terraform inputs

### Root plataforma (`infra/vars.tf`)

| Input | Obrigatoriedade/default | Finalidade; workflow/origem |
|---|---|---|
| `project_name` | Opcional; default `autoflow`; workflow define `autoflow` ou `autoflow-production` | Deriva nomes do cluster/node group e tags de descoberta da VPC, route tables, EIP/NAT, Security Group e subnets. O valor `autoflow` preserva a identificação existente de homologação. |
| `region_default` | Opcional; `us-east-1` | Região; workflow mapeia `AWS_REGION`. |
| `aws_profile` | Opcional; `null` | Perfil AWS local. |
| `aws_allowed_account_ids` | Obrigatório; sem default, lista não vazia de IDs de 12 dígitos | Guard do provider e dos backends/remote states S3; o workflow deriva a lista da variável externa `AWS_EXPECTED_ACCOUNT_ID`. |
| `cidr_vpc` | Opcional; `10.0.0.0/16` | Endereçamento VPC. |
| `cluster_role_arn`, `node_role_arn`, `operator_access_role_arn` | Obrigatórios, sem default | `pipeline.yml` descobre as roles de cluster e nodes por STS/IAM; localmente, forneça os `TF_VAR_*` após executar o preflight de descoberta. A role operador é derivada da sessão STS. O Apply valida as roles embutidas no Plan aprovado, sem redescobri-las. |
| `instance_type` | Opcional; `t3.medium` | Tipo de instância node. |
| `node_min_size`, `node_desired_size`, `node_max_size` | Opcionais; `2`, `2`, `3` | Tamanho node group. |
| `cluster_endpoint_private_access`, `cluster_endpoint_public_access` | Opcionais; `true`, `true` | Acesso endpoint EKS. |
| `cluster_endpoint_public_access_cidrs` | Opcional; default `189.6.8.245/32`; validação exige CIDR se endpoint público habilitado | CIDR permanente inicial do endpoint. Terraform ignora drift nesse atributo; o workflow gerencia o `/32` temporário do runner e preserva os CIDRs preexistentes ao limpar o lease. |
| `create_nat_gateway`, `create_operator_access_entry` | Opcionais; `true`, `true` | Controlam criação de recursos. |

Para descoberta local no PowerShell, configure primeiro `AWS_PROFILE`, `AWS_REGION` e `AWS_EXPECTED_ACCOUNT_ID` e use o nome de cluster correspondente ao ambiente:

```powershell
$projectName = "autoflow" # Produção: autoflow-production
$clusterName = "eks-$projectName"
$rolesJson = python scripts/verify_eks_iam_roles.py --discover --cluster $clusterName --region $env:AWS_REGION --expected-account $env:AWS_EXPECTED_ACCOUNT_ID
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
| `infra_state_key` | Obrigatório; sem default | State plataforma do mesmo Environment; `AWS_TF_STATE_KEY_INFRA`. |
| `cluster_name`, `nodegroup_name` | Derivados no workflow do Environment | Homologação usa `eks-autoflow`/`nodeg-autoflow`; produção usa `eks-autoflow-production`/`nodeg-autoflow-production`. O workflow valida os recursos exatos e status `ACTIVE`. |
| `lambda_function_name` | Derivado no workflow do Environment | `autoflow-cpf-validator-homolog` ou `autoflow-cpf-validator-production`, validada por consulta AWS. |
| `cors_origins` | `[]` | Origens CORS; `API_GATEWAY_CORS_ORIGINS`. |
| `alarm_actions` | `[]` | ARNs SNS opcionais; vazio não configura notificações. Workflow atual não injeta esta variável. |

## Referências indiretas

`api-gateway.yml` verifica checkout do repositório `autoflow` (padrão ref `develop`), controllers/allowlist, cluster e node group correspondentes ao Environment, status `ACTIVE` e state remoto do mesmo ambiente. O primeiro Plan/Apply de produção exige dispatch explícito; depois da criação do state, pushes correspondentes em `main` podem seguir CD. Não cadastrar `EKS_CLUSTER_NAME`, `EKS_NODEGROUP_NAME` nem `AWS_LAMBDA_FUNCTION_NAME`. `scripts/review_gateway_plan.py` consome `TF_VAR_expected_account_id`. Os GitHub `AWS_*` são mapeados para Terraform inputs `aws_*`; não são todos nomes idênticos.

**Fontes:** `.github/workflows/pipeline.yml`, `.github/workflows/api-gateway.yml`, `infra/vars.tf`, `infra/api-gateway/variables.tf`, scripts de validação e `README.md`.
