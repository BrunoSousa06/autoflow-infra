# Infraestrutura do AutoFlow

Este repositório declara a infraestrutura AWS do AutoFlow com Terraform. A arquitetura final é **Amazon API Gateway HTTP API, Lambda, VPC Link, ALB interno, EKS e RDS PostgreSQL**. Não há instalação ou roteamento Kong na configuração operacional.

## Documentação da arquitetura

Leia na ordem: [arquitetura e diagramas C4](docs/api-gateway/arquitetura.md), [ADR-001](docs/api-gateway/adr-001-api-gateway.md), [RFC técnica](docs/api-gateway/rfc-api-gateway.md), [runbook operacional](docs/api-gateway/runbook.md). O [README do root Terraform](infra/api-gateway/README.md) contém validações locais.

Para configurar Actions e inputs Terraform, consulte o [catálogo de variables e secrets](docs/variables-and-secrets.md) e seu [histórico](docs/variables-changelog.md).

Para investigar nós EC2 que não registram no Kubernetes, consulte o [runbook de diagnóstico e recuperação EKS](docs/eks-node-recovery.md). O procedimento é somente leitura até a seção explícita de recuperação manual; não há reboot automatizado.

Para diagnóstico dos nós EKS, consulte o [runbook](docs/eks-node-recovery.md). O provisionamento da EC2 runner está descrito em [Runner privado do GitHub Actions](docs/github-runner.md).

## Responsabilidades

- `infra/`: VPC, subnets, Security Groups, EKS e node group.
- `infra/api-gateway/`: HTTP API, rotas, integração nativa com Lambda, VPC Link, ALB interno, Target Groups e observabilidade.
- `autoflow`: Deployments, Services internos e NodePorts privados consumidos pelo ALB.
- `autoflow-lambda`: função de autenticação e execução em rede privada.
- `autoflow-db`: RDS PostgreSQL e controles de rede.

## Fluxo de requisições

```mermaid
flowchart LR
  Browser[Navegador] -->|HTTPS| API[API Gateway HTTP API]
  API -->|AWS_PROXY payload 2.0| Lambda[Lambda de autenticação]
  Lambda --> RDS[(RDS PostgreSQL)]
  API -->|VPC Link| ALB[ALB interno]
  ALB -->|NodePorts privados| EKS[EKS: Nginx e Spring Boot]
  EKS --> RDS
```

O navegador usa a mesma origem HTTPS para frontend e API. O API Gateway invoca a Lambda diretamente; as integrações de negócio e frontend usam VPC Link e ALB interno. A Function URL antiga foi removida; a invocação da Lambda ocorre pela permissão restrita ao API Gateway.

## Ordem de implantação

Implante ou confirme dependências nesta ordem, respeitando os states e owners existentes: (1) VPC/EKS e rede; (2) RDS e conectividade privada; (3) função Lambda e configuração segura; (4) aplicação no EKS (Services e NodePorts esperados pelo ALB); (5) API Gateway, VPC Link e ALB interno; (6) smoke tests ponta a ponta. Esta ordem decorre das dependências declaradas nos Terraform; não representa uma execução comprovada em conta nova. O procedimento detalhado e as condições de reprodução estão no [runbook](docs/api-gateway/runbook.md).

## States e pipelines

Os componentes usam states S3 separados: infraestrutura EKS, aplicação, RDS, Lambda e API Gateway. Confirme conta, região, bucket, key e state autoritativo antes de inicializar cada root. Não inicialize state vazio sobre recursos existentes e não edite arquivos de state manualmente.

CI executa em PRs para `develop`/`main` e em pushes para `develop`, `main` e `feature/**`. Em feature branches, os jobs executam validações e Terraform Plan especulativo sob o Environment `homolog`; o plan não é publicado como artifact, não pode ser consumido por Apply e as exclusões/substituições não são autorizadas. Também é possível iniciar `workflow_dispatch` selecionando a feature branch e mantendo `apply` desmarcado. O Apply de VPC/EKS continua restrito ao fluxo existente de `develop`/`main`, com aprovação no Environment correspondente, e o Apply de API Gateway continua restrito a `develop`. Os fluxos incluem verificação de conta/state e gates destrutivos; Required reviewers precisam estar configurados efetivamente no GitHub. O workflow de criação automática de PRs é restrito a pushes em `main`, para que um push de feature não abra PR antes de a branch estar pronta. Consulte a [RFC](docs/api-gateway/rfc-api-gateway.md) e o [runbook](docs/api-gateway/runbook.md). Nenhum workflow instala gateways adicionais.

Use `AWS_PROFILE`, `AWS_REGION`, `AWS_EXPECTED_ACCOUNT_ID` e `TF_VAR_*` localmente. O guard `scripts/verify_aws_account.py` deve passar antes de operações AWS. GitHub Actions Variables contêm conta, região, bucket, keys e parâmetros não sensíveis; credenciais e dados sensíveis permanecem em GitHub Secrets.
