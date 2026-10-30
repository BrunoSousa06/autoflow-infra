# Execução do Terraform em runners GitHub-hosted

O workflow de VPC/EKS usa `ubuntu-latest` tanto no Plan quanto no Apply. O root Terraform não provisiona mais uma EC2 runner nem requer GitHub App, PAT ou Secrets Manager para registrar runners.

## Acesso temporário ao endpoint EKS

Antes de executar Terraform, o workflow consulta o IP IPv4 de saída real do job e adiciona somente esse endereço como `/32` à allowlist pública de `eks-autoflow` em `us-east-1`. A atualização é consultada até terminar antes de prosseguir. O script captura e preserva a lista atual, incluindo `189.6.8.245/32`, e remove o CIDR temporário em etapa `always()` após Plan ou Apply. A concorrência do workflow é serializada sem cancelar uma execução em andamento.

O endpoint privado permanece habilitado. O CIDR permanente inicial está definido em `cluster_endpoint_public_access_cidrs` como `189.6.8.245/32`; Terraform ignora alterações externas somente nesse atributo para não reverter leases temporários. O endereço do runner é temporário e pode variar entre execuções. Um lease durável é gravado no S3 antes da alteração; se a execução for cancelada antes do cleanup, o próximo Plan/Apply reconcilia o lease anterior antes de criar outro. Cleanup sem objeto de lease termina sem alterar CIDRs. Erros S3 de credencial expirada, acesso negado, conectividade e falhas inesperadas são reportados distintamente; não causam remoção de CIDRs. Leases inválidos ou sem o CIDR permanente também bloqueiam qualquer alteração. O endpoint não admite `0.0.0.0/0`.

## Plan, aprovação e Apply

O Plan é armazenado como artifact criptografado por AES-256, com passphrase em secret do GitHub, checksum e commit associado. O Apply baixa o artifact exclusivamente da mesma execução, verifica o commit/checksum e aplica exatamente o arquivo aprovado. O job de Apply usa o environment `homolog`, cuja regra **Required reviewers** precisa estar realmente configurada. Exclusões e substituições continuam bloqueadas a menos que `allow_destructive` seja explicitamente selecionado no dispatch.

## Configuração necessária no GitHub

No repositório `autoflow-infra`, configure no GitHub Environment selecionado (`homolog` ou `production`) `AWS_REGION`, `AWS_EXPECTED_ACCOUNT_ID`, `AWS_TERRAFORM_STATE_BUCKET` e `AWS_TF_STATE_KEY_INFRA`. A key precisa usar o prefixo do Environment e seu sufixo é definido externamente. O workflow rejeita configuração ausente no Environment, ainda que exista uma Repository Variable com o mesmo nome. Configure também nesse Environment os Secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` e `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE`; não use um conjunto de credenciais de escopo de repositório compartilhado entre ambientes.

O Plan descobre uma única Cluster Role e Node Role na conta validada por STS, conferindo trust policies e AWS managed policies obrigatórias; os ARNs não são cadastrados manualmente. O Apply valida e reutiliza os ARNs embutidos no Plan aprovado, sem redescobrir ou substituir roles. A role operador não é cadastrada: cada job a resolve pela sessão AWS atual com `sts:GetCallerIdentity` e `iam:ListRoles`, exigindo correspondência única de conta, RoleId e separação das roles EKS.

Configure `homolog` para `develop` e `production` para `main`, com Required reviewers em ambos. O Plan e o Apply são associados ao Environment e consultam reviewers via `GITHUB_TOKEN`; o Apply aguarda a aprovação nativa. A execução production também exige `github.ref_protected`. A role AWS dos Environment Secrets precisa permitir consultar o cluster, atualizar a configuração do endpoint, consultar o status da atualização, usar o State S3 e executar as operações planejadas pelo Terraform. Também precisa de `s3:GetObject`, `s3:PutObject` e `s3:DeleteObject` no objeto de lease do bucket para a reconciliação durável.

## Limites de validação

As configurações locais declaram o comportamento acima; ele não comprova a implantação. Não foram feitas alterações reais na AWS. A allowlist base deve conter o CIDR existente `189.6.8.245/32` e quaisquer outros CIDRs permanentes previamente autorizados. Os CIDRs do EKS não carregam metadados de propriedade; por isso a reconciliação depende do lease único no S3 e da serialização dos jobs neste workflow.
