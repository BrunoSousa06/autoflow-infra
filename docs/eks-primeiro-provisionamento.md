# Provisionamento dos ambientes AWS

Os workflows dos quatro repositórios são independentes. Execute o provisionamento para cada ambiente, mantendo
`develop`/`homolog` separado de `main`/`production` e usando um Terraform State distinto por root.

## Preparação

1. Configure GitHub Environments `homolog` e `production`, com Variables e Secrets próprios, Required reviewers e
   restrições respectivas a `develop` e `main`. Proteja também a branch `main`. Defina
   `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true` somente após preparar as proteções.
2. Configure bucket e State Keys exclusivos para os seis roots (`vpc_eks`, `rds`, `lambda`, `application`, `api_gateway` e
   `newrelic`). Valide a matriz externa com
   `python scripts/terraform_state_contract.py <caminho-externo-para-configuracao.json>`.
3. Se o bucket de State ainda não existir, execute o [bootstrap isolado](state-bucket-bootstrap.md) com
   `approve_state_bucket_creation=true`. Esse dispatch não inicia Terraform Plan ou Apply.

## Ordem de provisionamento

Para cada ambiente, gere e revise o Plan de cada root antes de solicitar Apply:

1. `autoflow-infra`: VPC, rede, EKS e node group (`Pipeline`).
2. `autoflow-db`: RDS PostgreSQL privado.
3. `autoflow-lambda`: função de autenticação, que consome os States de VPC/EKS e RDS.
4. `autoflow-infra`: HTTP API, VPC Link e ALB (`Migração HTTP API`), após EKS e Lambda.
5. `autoflow`: aplicação Kubernetes, após RDS e API Gateway.
6. `autoflow-infra`: New Relic, após os workloads e seus Secrets estarem prontos.

`develop` seleciona `homolog`; `main` seleciona `production`. Cada workflow associa Plan/Apply ao Environment selecionado.
Apply requer `workflow_dispatch` com `apply=true`, os guards do root e aprovação do Environment. O fluxo de CI/CD está em
[Início automático do CD](ci-cd-automatico.md); os detalhes de cada State estão em
[arquitetura — States e ownership](api-gateway/arquitetura.md#states-e-ownership).

Não compartilhe State entre ambientes, não inicialize State vazio sobre recursos existentes e não aplique um Plan
produzido antes de mudanças de configuração ou State.
