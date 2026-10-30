# Execução do Terraform em runners GitHub-hosted

O workflow de VPC/EKS usa `ubuntu-latest` tanto no Plan quanto no Apply. O root Terraform não provisiona mais uma EC2 runner nem requer GitHub App, PAT ou Secrets Manager para registrar runners.

## Acesso temporário ao endpoint EKS

Antes do Plan/Apply, o workflow seleciona o cluster do Environment (`eks-autoflow` em homologação e `eks-autoflow-production` em produção), consulta o IP IPv4 de saída real do job e adiciona somente esse endereço como `/32` à allowlist pública. A atualização é consultada até terminar antes de prosseguir. O script captura e preserva a lista atual, incluindo os CIDRs permanentes declarados, e remove o CIDR temporário em etapa `always()` após Plan ou Apply. A concorrência do workflow é serializada sem cancelar uma execução em andamento.

O endpoint privado permanece habilitado. O CIDR permanente inicial está definido em `cluster_endpoint_public_access_cidrs` como `189.6.8.245/32`; Terraform ignora alterações externas somente nesse atributo para não reverter leases temporários. O endereço do runner é temporário e pode variar entre execuções. Um lease durável é gravado no S3 antes da alteração; se a execução for cancelada antes do cleanup, o próximo Plan/Apply reconcilia o lease anterior antes de criar outro. Cleanup sem objeto de lease termina sem alterar CIDRs. Erros S3 de credencial expirada, acesso negado, conectividade e falhas inesperadas são reportados distintamente; não causam remoção de CIDRs. Leases inválidos ou sem o CIDR permanente também bloqueiam qualquer alteração. O endpoint não admite `0.0.0.0/0`.

## Plan, aprovação e Apply

O Plan é armazenado como artifact criptografado por AES-256, com passphrase em secret do GitHub, checksum, fingerprint e commit/run associados. O Apply baixa o artifact exclusivamente da mesma execução, verifica esses vínculos e aplica exatamente o arquivo aprovado. Os jobs Plan e Apply usam o Environment selecionado; a proteção nativa desse Environment continua responsável por aguardar Required reviewers. Em `main`, a branch também precisa estar protegida. Exclusões e substituições continuam bloqueadas a menos que `allow_destructive` seja explicitamente selecionado no dispatch.

O bootstrap do backend S3 é um job independente: `workflow_dispatch` com `approve_state_bucket_creation=true` exige a aprovação nativa do Environment. Esse dispatch ignora `validate`, Plan, Apply e Terraform init. Antes da execução, o preflight valida os valores não vazios recebidos diretamente dos contextos `vars` e `secrets`, a conta, região, bucket e o gate adicional `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`. Deixe `apply`, `approve_eks_state_reconciliation` e `allow_destructive` em `false`; detalhes e comandos documentais estão no [runbook do bucket](state-bucket-bootstrap.md).

## Configuração necessária no GitHub

No repositório `autoflow-infra`, configure em cada GitHub Environment (`homolog` ou `production`) `AWS_REGION`, `AWS_EXPECTED_ACCOUNT_ID`, `AWS_TERRAFORM_STATE_BUCKET`, as State Keys do root e `TERRAFORM_APPLY_APPROVAL_CONFIGURED`. As State Keys precisam usar o prefixo do Environment e ter sufixos distintos por root. Os preflights verificam valores não vazios e não consultam APIs administrativas para listar Variables ou Secrets. Configure também em cada Environment os Secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` e `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE`; as credenciais AWS são validadas contra a conta esperada antes de operações AWS.

O Plan descobre uma única Cluster Role e Node Role na conta validada por STS, conferindo trust policies e AWS managed policies obrigatórias; os ARNs não são cadastrados manualmente. O Apply valida e reutiliza os ARNs embutidos no Plan aprovado, sem redescobrir ou substituir roles. A role operador não é cadastrada: cada job a resolve pela sessão AWS atual com `sts:GetCallerIdentity` e `iam:ListRoles`, exigindo correspondência única de conta, RoleId e separação das roles EKS.

Configure `homolog` para `develop` e `production` para `main`, com Required reviewers e políticas de branch no próprio GitHub Environment. Os jobs Plan, Apply e bootstrap permanecem associados ao Environment selecionado; não há consulta administrativa dessas regras pela pipeline. Antes de definir `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`, uma identidade administrativa autorizada deve confirmar externamente a lista de Required reviewers e a política de branches. Consulte o procedimento abaixo. A execução production também exige `github.ref_protected`. A role AWS dos Environment Secrets precisa permitir consultar o cluster, atualizar a configuração do endpoint, consultar o status da atualização, usar o State S3 e executar as operações planejadas pelo Terraform. Também precisa de `s3:GetObject`, `s3:PutObject` e `s3:DeleteObject` no objeto de lease do bucket para a reconciliação durável.

## Auditoria administrativa externa

A chamada da REST API de GitHub Environments pela pipeline retornou HTTP 403 (`Resource not accessible by integration`) para `GITHUB_TOKEN`. Os workflows não usam PAT administrativo, permissões elevadas ou outro token para contornar essa restrição. A aprovação continua sendo aplicada pelo mecanismo nativo do Environment; a configuração efetiva de reviewers deve ser auditada fora da pipeline antes de habilitar o gate adicional.

Use uma sessão administrativa aprovada, com autorização de leitura da configuração de Environments (por exemplo, permissão `administration:read` quando aplicável), fora do GitHub Actions. O comando abaixo consulta apenas metadados e informa erro se algum Environment não tiver reviewers:

```bash
for environment in homolog production; do
  gh api "repos/autoflow-fiap/autoflow-infra/environments/$environment" --jq '
    [.protection_rules[]? | select(.type == "required_reviewers") | .reviewers[]?] as $reviewers
    | if ($reviewers | length) == 0 then error("Required reviewers ausentes") else
      {
        environment: .name,
        required_reviewers_count: ($reviewers | length),
        deployment_branch_policy: .deployment_branch_policy
      }
      end'
done
```

Confirme que `homolog` permite o fluxo esperado de `develop`, que `production` está restrito a `main`, que os reviewers são identidades/grupos autorizados e que a branch `main` tem proteção efetiva. Se `deployment_branch_policy` indicar políticas customizadas, confira também na configuração do Environment quais branches estão permitidas. Só depois dessa auditoria defina `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true` separadamente em cada Environment. Não copie credenciais para o repositório ou para os workflows; não use a auditoria para alterar reviewers, branches ou aprovações automaticamente.

## Limites de validação

As configurações locais declaram o comportamento acima; ele não comprova a implantação. Não foram feitas alterações reais na AWS. A allowlist base deve conter o CIDR existente `189.6.8.245/32` e quaisquer outros CIDRs permanentes previamente autorizados. Os CIDRs do EKS não carregam metadados de propriedade; por isso a reconciliação depende do lease único no S3 e da serialização dos jobs neste workflow.
