# Infraestrutura do AutoFlow

Este repositório declara, por Terraform, a infraestrutura compartilhada do AutoFlow: rede, cluster EKS e a instalação do Kong Gateway OSS com Kong Ingress Controller (KIC). A configuração versionada não comprova que os recursos foram criados ou estão ativos na AWS.

## Responsabilidades

- `infra/`: VPC, subnets, Security Groups, EKS e node group.
- `infra/kong/`: root Terraform independente que instala Kong OSS/KIC por Helm no cluster existente.
- `autoflow`: mantém Deployments, Services, Ingresses e `KongPlugin` específicos da aplicação.
- `autoflow-db`: mantém RDS e seus controles de rede; `autoflow-lambda` mantém a função e a integração API Gateway HTTP legada.

## Kong

O root `infra/kong/` fixa versões do chart e das imagens, configura o Gateway em modo DB-less e habilita o plugin `aws-lambda`. O proxy está configurado como Service `ClusterIP`; este release não publica uma entrada HTTPS. O Admin API, Manager e Portal estão desabilitados.

As rotas são mantidas no repositório `autoflow` e não são aplicadas por este root. IRSA para invocar a Lambda, endpoint público, TLS/DNS e execução em cluster permanecem gates pendentes. A configuração e os comandos de validação local estão no [README do root Kong](infra/kong/README.md). Testes locais de template/validação não comprovam instalação ou tráfego em AWS.

## Terraform e pipelines

Há roots e states independentes para a infraestrutura EKS e para Kong. Antes de inicializar ou planejar um backend remoto, confirme com os responsáveis o bucket, a key e o state autoritativo; não inicialize state vazio sobre recursos existentes. O workflow de Kong depende da etapa de infraestrutura e de readiness do cluster. Não execute roots que atuam no mesmo cluster em paralelo.

Nenhum `.tfvars` ou backend HCL de exemplo é versionado. Em execução local, forneça `AWS_PROFILE`, `AWS_REGION`, `AWS_EXPECTED_ACCOUNT_ID`, `TF_VAR_aws_profile`, `TF_VAR_aws_allowed_account_ids` (JSON de uma lista) e os ARNs não secretos das roles por `TF_VAR_*`. O guard `scripts/verify_aws_account.py` deve passar antes de operações AWS. Para cada root, passe bucket e key aprovados como parâmetros `-backend-config`; infra e Kong usam keys distintas. CI/CD usa GitHub Actions Variables para conta, região, bucket, keys e ARNs, e GitHub Secrets para as credenciais AWS configuradas no runner.

## Segurança e custos VPC/EKS

A revisão pré-deploy, o progresso, os parâmetros por ambiente e os gates de readiness estão em [Segurança de rede e custos VPC/EKS](infra/SEGURANCA-CUSTOS-READINESS.md). O deploy permanece pendente da revisão de um novo plano com parâmetros e state aprovados.

## Validação local do Kong

Com Terraform e Helm `3.19.0` disponíveis, no diretório `infra/kong/`:

```bash
bash ./validate.sh
terraform init -backend=false -input=false
terraform fmt -check -recursive
terraform validate
```

Esses comandos validam localmente a configuração e os templates. Não aplicam recursos, não consultam o EKS nem verificam autorização AWS. Nenhum deploy ou alteração AWS é comprovado por este README.
