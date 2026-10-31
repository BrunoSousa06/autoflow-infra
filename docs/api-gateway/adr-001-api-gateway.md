# ADR-001 — API Gateway HTTP API v2

- **Data:** 13/10/2026
- **Status:** Aceita.

## Decisão

Usar Amazon API Gateway HTTP API v2 como entrada pública do AutoFlow. `POST /auth/login` integra com a Lambda por
`AWS_PROXY`, payload 2.0. Frontend e rotas de negócio usam `HTTP_PROXY` pelo VPC Link v2 até um ALB interno, que encaminha
ao EKS. Lambda e backend acessam o RDS PostgreSQL privado. A Lambda emite JWT HS256; o backend valida o token e aplica a
autorização de domínio.

## Consequências

- A camada pública e a integração de login usam serviços gerenciados; os serviços de negócio permanecem em rede privada.
- A autorização de domínio continua no Spring Boot, que consulta perfil e estado do usuário.
- API Gateway, VPC/EKS, New Relic, aplicação, Lambda e RDS usam Terraform States independentes.
- Mudanças de infraestrutura são planejadas e aplicadas pelos workflows do repositório, com o Plan vinculado à execução.

## Provisionamento do backend Terraform

A criação ou verificação inicial do bucket S3 é um job isolado do workflow `Pipeline`, iniciado por
`workflow_dispatch` com `approve_state_bucket_creation=true`. Esse dispatch não executa Terraform Plan ou Apply. Consulte
o [runbook de bootstrap](../state-bucket-bootstrap.md).
