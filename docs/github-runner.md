# Execução do Terraform em runners GitHub-hosted

O workflow de VPC/EKS usa `ubuntu-latest` tanto no Plan quanto no Apply. O root Terraform não provisiona mais uma EC2 runner nem requer GitHub App, PAT ou Secrets Manager para registrar runners.

## Acesso temporário ao endpoint EKS

Antes de executar Terraform, o workflow consulta o IP IPv4 de saída real do job e adiciona somente esse endereço como `/32` à allowlist pública de `eks-autoflow` em `us-east-1`. A atualização é consultada até terminar antes de prosseguir. O script captura e preserva a lista atual, incluindo `189.6.8.245/32`, e remove o CIDR temporário em etapa `always()` após Plan ou Apply. A concorrência do workflow é serializada sem cancelar uma execução em andamento.

O endpoint privado permanece habilitado. O endereço do runner é temporário e pode variar entre execuções. Um lease durável é gravado no S3 antes da alteração; se a execução for cancelada antes do cleanup, o próximo Plan/Apply reconcilia o lease anterior antes de criar outro. O endpoint não admite `0.0.0.0/0`.

## Plan, aprovação e Apply

O Plan é armazenado como artifact criptografado por AES-256, com passphrase em secret do GitHub, checksum e commit associado. O Apply baixa o artifact exclusivamente da mesma execução, verifica o commit/checksum e aplica exatamente o arquivo aprovado. O job de Apply usa o environment `homolog`, cuja regra **Required reviewers** precisa estar realmente configurada. Exclusões e substituições continuam bloqueadas a menos que `allow_destructive` seja explicitamente selecionado no dispatch.

## Configuração necessária no GitHub

No repositório `autoflow-infra`, configure como Repository Variables `AWS_REGION=us-east-1`, `AWS_EXPECTED_ACCOUNT_ID`, `AWS_TERRAFORM_STATE_BUCKET`, `AWS_TF_STATE_KEY_INFRA`, `AWS_EKS_CLUSTER_ROLE_ARN`, `AWS_EKS_NODE_ROLE_ARN` e `AWS_EKS_OPERATOR_ACCESS_ROLE_ARN`. Configure como Repository Secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` e `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE` (valor forte e compartilhado entre Plan/Apply). Não duplique esses valores no Environment `homolog`, para que Plan e Apply recebam exatamente as mesmas configurações de repositório.

Crie somente `homolog`, restrinja-o a `develop` e configure Required reviewers. O Plan não usa Environment; o Apply pausa na proteção real de `homolog` e também consulta reviewers via `GITHUB_TOKEN`. A role AWS dos Repository Secrets precisa permitir consultar o cluster, atualizar a configuração do endpoint, consultar o status da atualização, usar o state S3 e executar as operações planejadas pelo Terraform. Também precisa de `s3:GetObject`, `s3:PutObject` e `s3:DeleteObject` no objeto `ci/eks-endpoint-lease.json` do bucket de state para a reconciliação durável.

## Limites de validação

As configurações locais declaram o comportamento acima; ele não comprova a implantação. Não foram feitas alterações reais na AWS. A allowlist base deve conter o CIDR existente `189.6.8.245/32` e quaisquer outros CIDRs permanentes previamente autorizados. Os CIDRs do EKS não carregam metadados de propriedade; por isso a reconciliação depende do lease único no S3 e da serialização dos jobs neste workflow.
