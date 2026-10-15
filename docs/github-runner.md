# Runner privado do GitHub Actions

## Provisionamento

O root `infra` contém a EC2 dedicada `autoflow-github-runner`. A criação é opt-in por `create_github_runner` (default `false`), para que planos existentes de VPC/EKS não criem instâncias implicitamente. A instância usa Ubuntu 24.04, tipo `t3.small` por default, disco `gp3` criptografado, IMDSv2 obrigatório, subnet privada já declarada pelo root e sem IP público.

O Security Group novo não permite entrada e autoriza saída TCP 443. Uma regra de entrada TCP 443 na Security Group de controle do EKS permite tráfego somente a partir do Security Group do runner; não altera os nós existentes nem os CIDRs do endpoint. A subnet privada precisa ter rota/saída HTTPS funcional via NAT já existente. Não há criação de NAT neste recurso.

Ao aplicar o root `autoflow-infra/infra` com `create_github_runner=true`, configure também:

| Terraform input / GitHub Variable | Valor |
| --- | --- |
| `github_runner_repository` | URL HTTPS de um único repositório; o pipeline define `https://github.com/BrunoSousa06/autoflow` |
| `github_app_id` / `RUNNER_APP_ID` | ID numérico da GitHub App |
| `github_app_installation_id` / `RUNNER_APP_INSTALLATION_ID` | Instalação da App no repositório `autoflow` |
| `github_app_private_key_secret_arn` / `RUNNER_APP_KEY_SECRET_ARN` | ARN de um segredo Secrets Manager cujo `SecretString` contém a chave privada PEM da App |
| `CREATE_GITHUB_RUNNER` | `true` para incluir a EC2 no plan aprovado; default `false` |

A GitHub App deve estar instalada somente no repositório `autoflow` e possuir permissão de repositório **Administration: write**, necessária para emitir tokens curtos de registro. Crie/popule o segredo Secrets Manager antes de habilitar o runner; a role EC2 recebe apenas `secretsmanager:GetSecretValue` nesse ARN. A chave privada nunca é passada como user-data nem gravada no Terraform state. O runner gera JWT e registration token durante o boot, usa os arquivos somente em `/run` e remove-os ao terminar o registro.

O serviço `systemd` baixa a versão estável corrente do runner oficial, registra um runner `--ephemeral` com label `autoflow-eks`, executa um job e reinicia para registrar um token novo. O runner é restrito ao repositório, sem listener de entrada; não instala Docker nem recebe acesso `sudo`, e uma regra local bloqueia o usuário do runner do endpoint IMDS. Não encaminhar jobs de PRs/forks nem workflows não confiáveis a essa label; no pipeline atual, os jobs privados rodam somente por `workflow_dispatch` na branch `develop`.

## Habilitação do deploy

1. Conferir IAM/SCP, permissão `iam:PassRole`, criação de EC2/instance profile/SG e permissões Secrets Manager no Learner Lab; validar limite/custo e saída HTTPS da subnet privada.
2. Criar e instalar a GitHub App no único repositório autorizado; armazenar a chave privada no Secrets Manager e configurar as três GitHub Variables da App.
3. Configurar `CREATE_GITHUB_RUNNER=true`, revisar o plan do root `autoflow-infra/infra` e aplicar somente após aprovação operacional pelo fluxo existente.
4. Confirmar status `Online` e label `autoflow-eks` no GitHub, além da conectividade privada e identidade AWS esperada.
5. Criar o Environment `homolog-plan` sem required reviewers, com branch permitida `develop`, e duplicar nele as variables e os secrets AWS necessários ao plan. Criar o Environment `homolog` com branch permitida `develop` e Required reviewers efetivos; configurar nele as variables/secrets usados no Apply e Secret Kubernetes. `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true` é apenas uma verificação adicional.
6. Publicar as imagens SHA por push em `develop`; então executar manualmente o workflow `Pipeline` em `develop` para revisar o resumo redigido do plan. O job de Apply aguarda aprovação do Environment `homolog`, baixa o artifact criptografado da mesma execução, valida seus hashes/configuração e aplica exatamente o `.tfplan` recebido, sem executar outro `terraform plan`. O artifact tem retenção de um dia e o rollout dos deployments backend e frontend é aguardado.

O fluxo depende de credenciais AWS temporárias válidas nos secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_SESSION_TOKEN`. Atualize as três antes da execução se o Learner Lab tiver expirado a sessão. O cadastro da EC2 não provisiona IAM para acesso ao cluster; a identidade fornecida ao job precisa já estar autorizada no EKS e no state S3.

## Limites conhecidos

Terraform não foi aplicado por esta implementação. Permissões de escrita/IAM, limites Academy, conectividade real do runner, GitHub App, Environment protection, identidade EKS e health do cluster não foram testados. A regra de SG adicionada destina-se ao endpoint do control plane; não é uma regra pública e não altera os CIDRs autorizados do endpoint.
