# ADR-001 — Substituição do Kong pelo Amazon API Gateway

- **Data:** 13/10/2026
- **Status:** Aceita; configuração declarada. A homologação registrada é anterior ao reset do Learner Lab.
- **Decisores:** Não registrado nos artefatos consultados

## Contexto

A arquitetura anterior usava Kong no EKS como entrada para login, frontend e API. A configuração atual declara Amazon API Gateway HTTP API v2 como entrada e não declara Kong como gateway operacional. O registro de homologação de 13/10/2026 é anterior ao reset do Learner Lab; ele não confirma a disponibilidade atual dos recursos. Consulte a seção [Registro histórico de homologação](arquitetura.md#registro-historico-homologacao).

## Decisão

Adotar Amazon API Gateway HTTP API v2 como entrada pública única. `POST /auth/login` integra diretamente com a Lambda por `AWS_PROXY` (payload 2.0); frontend e rotas de negócio usam `HTTP_PROXY` pelo VPC Link v2 para um ALB interno, que encaminha aos NodePorts privados do EKS. Lambda e backend acessam o RDS PostgreSQL privado. A Lambda emite JWT HS256 e o backend valida o token e aplica autorização de domínio.

## Alternativas consideradas

- **Manter Kong:** não escolhido; manteria um gateway operado no cluster e uma camada adicional de operação. Não há avaliação quantitativa comparativa registrada.
- **API Gateway com Lambda proxy em todas as rotas:** não escolhido; o desenho implantado mantém frontend e backend no EKS e os conecta pelo VPC Link/ALB.
- **Function URL para login:** rejeitada como caminho definitivo; foi removida e a invocação nativa ficou restrita à rota de login da HTTP API.

## Consequências

- A entrada pública e a integração de login são serviços gerenciados; as rotas privadas dependem de VPC Link, ALB, EKS, NodePorts e regras de Security Group coerentes.
- O API Gateway aplica throttling e registra metadados de acesso sem body, IP, query ou headers no formato atualmente configurado.
- A autorização de domínio continua no Spring Boot; o API Gateway não substitui a consulta de perfil/estado.
- O state do gateway é separado dos states de plataforma, aplicação, RDS e Lambda. Mudanças destrutivas exigem revisão de plano e aprovação operacional.
- A reversão ao Kong não é automática após sua retirada e requer reimplantação explícita, infraestrutura e aprovação.
