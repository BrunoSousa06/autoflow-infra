# ADR-001 — Substituição do Kong pelo Amazon API Gateway

- **Data:** 13/10/2026
- **Status:** Aceita; configuração declarada e provisionável segundo o código local. Implantação AWS não verificada nesta revisão.
- **Decisores:** Não registrado nos artefatos consultados

## Contexto

A arquitetura anterior usava Kong no EKS como entrada para login, frontend e API. A configuração final declara Amazon API Gateway HTTP API v2 como entrada e não declara Kong como gateway operacional. Após reset do Learner Lab, configure e valide os Environments, execute o bootstrap S3 isolado e depois as pipelines CI/CD na ordem descrita nos runbooks; esta sequência não comprova provisionamento atual.

## Decisão

Adotar Amazon API Gateway HTTP API v2 como entrada pública única. `POST /auth/login` integra diretamente com a Lambda por `AWS_PROXY` (payload 2.0); frontend e rotas de negócio usam `HTTP_PROXY` pelo VPC Link v2 para um ALB interno, que encaminha aos NodePorts privados do EKS. Lambda e backend acessam o RDS PostgreSQL privado. A Lambda emite JWT HS256 e o backend valida o token e aplica autorização de domínio.

## Alternativas consideradas

- **Manter Kong:** não escolhido; manteria um gateway operado no cluster e uma camada adicional de operação. Não há avaliação quantitativa comparativa registrada.
- **API Gateway com Lambda proxy em todas as rotas:** não escolhido; o desenho implantado mantém frontend e backend no EKS e os conecta pelo VPC Link/ALB.
- **Function URL da Lambda:** não é usada. O login entra pela HTTP API, que invoca a Lambda por `AWS_PROXY`; a permissão `lambda:InvokeFunction` é limitada à rota de login.

## Consequências

- A entrada pública e a integração de login são serviços gerenciados; as rotas privadas dependem de VPC Link, ALB, EKS, NodePorts e regras de Security Group coerentes.
- O API Gateway aplica throttling e registra metadados de acesso sem body, IP, query ou headers no formato atualmente configurado.
- A autorização de domínio continua no Spring Boot; o API Gateway não substitui a consulta de perfil/estado.
- O state do gateway é separado dos states de plataforma, aplicação, RDS e Lambda. Mudanças destrutivas exigem revisão de plano e aprovação operacional.
- A reversão ao Kong não é automática após sua retirada e requer reimplantação explícita, infraestrutura e aprovação.

## Evolução operacional do backend Terraform — 30/10/2026

A decisão deste ADR sobre API Gateway permanece inalterada. Separadamente, a criação do bucket de backend S3 foi removida do fluxo Plan da VPC/EKS e passou a um job independente do workflow `Pipeline`, iniciado somente por `workflow_dispatch` com `approve_state_bucket_creation=true` e protegido pelo GitHub Environment correspondente. Esse job valida a identidade AWS e os controles do bucket; não executa Terraform e não dispara os jobs de Plan ou Apply. A Variable legada `APPROVE_CREATE` deixou de ser consumida. A alteração registra comportamento de código e testes locais, sem afirmar execução ou alteração de recursos na AWS.
