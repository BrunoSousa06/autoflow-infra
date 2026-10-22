# Arquitetura final: AutoFlow com Amazon API Gateway

**Data da evidência operacional:** 13/10/2026. **Status:** arquitetura declarada no Terraform e homologada somente no ambiente Learner Lab registrado em [progresso.md](progresso.md). Não há ambiente de produção implantado nesta arquitetura; segregação futura com segundo EKS/RDS permanece planejada. A configuração local, isoladamente, não comprova estado AWS.

Esta página consolida a arquitetura e os diagramas C4. A decisão arquitetural está registrada em [ADR-001](adr-001-api-gateway.md) e os detalhes de desenho/implantação em [RFC técnica](rfc-api-gateway.md).

## Decisão

1. Amazon API Gateway HTTP API v2 é a única entrada pública do AutoFlow.
2. `POST /auth/login` usa integração nativa `AWS_PROXY`, payload `2.0`, para a Lambda existente. A permissão `lambda:InvokeFunction` é restrita à conta e à rota.
3. Rotas de negócio e frontend usam integração `HTTP_PROXY` pelo VPC Link v2 para listeners de um ALB interno.
4. O ALB encaminha aos NodePorts `30081` (Spring Boot) e `30080` (Nginx/Angular), que seguem para Services e Pods do EKS.
5. Lambda e backend acessam o RDS PostgreSQL privado. O JWT HS256 emitido pela Lambda é validado pelo backend; perfis e estado do cliente são verificados no domínio.
6. A Function URL não participa do caminho de tráfego e foi removida por Terraform. A permissão de invocação nativa da HTTP API permanece; a Lambda não depende de Function URL.

## Evidência em homologação

API `4ct2k9m5l8`, stage `$default`, 79 rotas e 48 integrações. VPC Link `cjhmlk` `AVAILABLE`; ALB `autoflow-homolog-private` `active/internal`. Target Groups backend/frontend: 2/2 `healthy`. RDS disponível, backend `db:UP`, 47 migrations Flyway validadas e schema atualizado. Login válido de cliente seed, emissão de JWT e consulta autenticada pelo backend retornaram HTTP 200. Smokes de autenticação negativa, CORS não autorizado, assets e deep links também passaram.

Essas evidências descrevem o ambiente verificado em 13/10/2026; não substituem validação em outra conta ou região.

## C4 — contexto

```mermaid
flowchart LR
  U[Cliente e equipe da oficina] -->|HTTPS| API[Amazon API Gateway HTTP API]
  API -->|Login AWS_PROXY| L[Lambda de autenticação]
  API -->|VPC Link → ALB interno| APP[Frontend Angular e backend Spring Boot no EKS]
  APP -->|PostgreSQL| DB[(RDS PostgreSQL)]
  L -->|PostgreSQL| DB
```

## C4 — contêineres

```mermaid
flowchart LR
  Browser[Navegador Angular] -->|HTTPS, mesma origem| G[HTTP API / stage $default]
  G -->|POST /auth/login, payload 2.0| L[Lambda Python]
  G -->|HTTP_PROXY / VPC Link| ALB[ALB interno]
  ALB --> FE[NodePort 30080 / Nginx Angular]
  ALB --> BE[NodePort 30081 / Spring Boot]
  FE --> SPA[Bundles Angular]
  L --> DB[(RDS PostgreSQL privado)]
  BE --> DB
```

## C4 — componentes

```mermaid
flowchart LR
  subgraph API[Amazon API Gateway HTTP API]
    LOGIN[POST /auth/login<br/>AWS_PROXY payload 2.0]
    BUSINESS[Rotas de negócio\nHTTP_PROXY / VPC Link]
    STATIC[Rotas frontend\nHTTP_PROXY / VPC Link]
  end
  subgraph AUTH[Lambda de autenticação]
    VALIDATE[Validar cpf_cnpj e senha]
    CLIENT[Consultar usuário/cliente ativo]
    ISSUE[Emitir JWT HS256]
  end
  subgraph EKS[EKS atrás do ALB interno]
    NGINX[Nginx / Angular<br/>NodePort 30080]
    SPRING[Spring Boot<br/>NodePort 30081]
    FILTER[Filtro JWT e autorização de domínio]
  end
  DB[(RDS PostgreSQL privado)]
  LOGIN --> VALIDATE --> CLIENT --> DB
  CLIENT --> ISSUE
  BUSINESS --> SPRING --> FILTER
  STATIC --> NGINX
  FILTER -->|validar assinatura e carregar perfil| DB
```

O contrato atualmente documentado pela Lambda usa `cpf_cnpj` e `senha`. O diagrama não implica que o API Gateway valide JWT: a validação e autorização de domínio das rotas protegidas são feitas pelo backend Spring Boot.

## Sequências de comunicação

### 1. Login CPF/CNPJ e emissão de JWT

```mermaid
sequenceDiagram
  actor Cliente
  participant GW as API Gateway HTTP API
  participant L as Lambda de autenticação
  participant DB as RDS PostgreSQL
  participant FE as Frontend Angular
  Cliente->>FE: Informar CPF/CNPJ e senha
  FE->>GW: POST /auth/login {cpf_cnpj, senha}
  GW->>L: AWS_PROXY, payload 2.0
  L->>DB: Consultar usuário/cliente e validar senha/status
  DB-->>L: Registro e resultado da validação
  L-->>GW: HTTP 200 + JWT HS256 (ou erro de autenticação)
  GW-->>FE: Resposta de login
```

### 2. Acesso autenticado ao backend

```mermaid
sequenceDiagram
  actor Usuario as Usuario autenticado
  participant FE as Frontend Angular
  participant GW as API Gateway HTTP API
  participant ALB as ALB interno via VPC Link
  participant BE as Backend Spring Boot no EKS
  participant DB as RDS PostgreSQL
  Usuario->>FE: Acessar funcionalidade
  FE->>GW: GET rota protegida + Authorization: Bearer JWT
  GW->>ALB: HTTP_PROXY por VPC Link
  ALB->>BE: Listener backend → NodePort 30081
  BE->>BE: Validar assinatura, expiração e claims do JWT
  BE->>DB: Carregar perfil/estado e executar operação autorizada
  DB-->>BE: Dados autorizados
  BE-->>ALB: Resposta HTTP
  ALB-->>GW: Resposta
  GW-->>FE: Resposta da API
```

### 3. Acesso ao frontend Angular

```mermaid
sequenceDiagram
  actor Usuario as Usuario
  participant Browser as Navegador Angular
  participant GW as API Gateway HTTP API
  participant ALB as ALB interno via VPC Link
  participant Nginx as Nginx no EKS
  Usuario->>Browser: Abrir aplicação ou navegar para rota
  Browser->>GW: GET /, rota frontend ou asset
  GW->>ALB: HTTP_PROXY pelo VPC Link
  ALB->>Nginx: Listener frontend → NodePort 30080
  Nginx-->>ALB: HTML ou asset Angular
  ALB-->>GW: Resposta HTTP
  GW-->>Browser: HTML ou asset
```

As respostas negativas de login não geram JWT. Um JWT válido não substitui as verificações de perfil e estado do cliente no backend.

## C4 — implantação e rede

```mermaid
flowchart TB
  Client[Navegador] -->|HTTPS| API[Amazon API Gateway HTTP API]
  API -->|AWS_PROXY payload 2.0| Lambda[Lambda autenticação]
  API -->|VPC Link / ENIs| ALB[ALB interno em subnets privadas]
  subgraph VPC[VPC declarada: 3 subnets públicas e 3 privadas em 3 AZs]
    subgraph Privadas[Subnets privadas]
      ALB -->|listeners HTTP 8080/8081| TG[Target Groups]
      TG -->|SG ALB → SG nodes<br/>NodePorts 30080/30081| Nodes[Node group EKS]
      Nodes -->|Services → Pods| Apps[Deployments Angular/Nginx e Spring Boot]
      Lambda -->|PostgreSQL 5432| RDS[(RDS PostgreSQL)]
      Apps -->|PostgreSQL 5432| RDS
    end
    Publicas[Subnets públicas / Internet Gateway e rotas públicas]
  end
  LinkSG[SG VPC Link: saída para listeners ALB]
  AlbSG[SG ALB: entrada VPC Link; saída SG nodes]
  NodeSG[SG nodes: entrada NodePorts somente SG ALB]
  DbSG[SG RDS: PostgreSQL das origens configuradas]
  API -. controla .-> LinkSG
  LinkSG -.-> AlbSG
  AlbSG -.-> NodeSG
  DbSG -.-> RDS
```

Terraform declara três subnets públicas e três privadas distribuídas em três AZs; ALB interno, VPC Link, EKS e RDS usam subnets privadas conforme seus roots. O diagrama representa configuração declarada e não inventário atual. O SG do ALB permite o SG do VPC Link nos listeners 8080/8081 e saída ao SG dos nodes nas portas 30080/30081; os NodePorts aceitam tráfego somente do SG do ALB. O SG do RDS permite PostgreSQL às origens configuradas no root do banco. O tráfego privado VPC Link–ALB usa HTTP; TLS termina no endpoint gerenciado do API Gateway.

## Rotas e autorização

A matriz executável está em [`routes.tf`](../../infra/api-gateway/routes.tf): 56 rotas de backend, 22 de frontend e uma rota de login. Não há rota catch-all. Rotas de negócio exigem JWT e autorização do Spring; endpoints públicos são somente os declarados no contrato. O API Gateway não substitui a autenticação de domínio.

O frontend chama `/auth/login` e as rotas de negócio no mesmo host. `cors_origins` e `gateway_cors_origins` permanecem allowlists exatas HTTPS para eventuais origens externas; não se usa wildcard.

## States e ownership

| State | Responsabilidade final |
|---|---|
| `eks/terraform.tfstate` | VPC, EKS e node group |
| `application/autoflow/terraform.tfstate` | Deployments, Services, NodePorts e ConfigMaps da aplicação |
| `rds/terraform.tfstate` | RDS PostgreSQL e rede do banco |
| `lambda/terraform.tfstate` | Função Lambda e configuração de execução; Function URL e permissões públicas legadas removidas no checkpoint |
| `api-gateway/terraform.tfstate` | HTTP API, rotas, integração nativa Lambda, VPC Link, ALB, Target Groups e observabilidade |

Os states permanecem separados. Nenhum state deve ser editado diretamente ou compartilhado entre contas.

## 4. Fluxo de implantação declarado nos workflows

```mermaid
sequenceDiagram
  actor Dev as Desenvolvedor
  participant GH as GitHub Actions
  participant CI as CI em PR/push
  participant Env as Environment homolog
  participant TF as Terraform plan/gates
  participant AWS as AWS homolog
  Dev->>GH: PR ou push em develop/main
  GH->>CI: Executar testes e validações de CI
  CI-->>Dev: Resultado dos checks, sem Apply nesses eventos
  Dev->>GH: workflow_dispatch em develop com deploy=false
  GH->>Env: Job plan requer Environment homolog
  Env->>TF: Disponibilizar Secrets/Variables após eventuais proteções do Environment
  TF->>TF: Validar conta/state, gerar plan e aplicar gate de destruições
  TF-->>Dev: Resultado do plan para revisão fora do workflow
  Dev->>GH: Novo workflow_dispatch com deploy=true após revisão
  GH->>Env: Job de deploy requer Environment homolog
  Env->>TF: Iniciar job se as proteções efetivas permitirem
  TF->>TF: Revalidar state, regenerar plan e conferir gates
  TF->>AWS: Apply somente se guards e inputs permitirem
```

O diagrama descreve o fluxo definido em workflows, não uma execução ou implantação comprovada pelo GitHub Actions. A aprovação do GitHub Environment, se Required reviewers estiverem configurados, ocorre antes das etapas do job; o plan e o Apply não usam um mesmo plan previamente salvo entre despachos. A presença de `environment: homolog` e do guard `TERRAFORM_APPLY_APPROVAL_CONFIGURED` não comprova Required reviewers configurados; essa configuração efetiva permanece **não verificada**. Logo, atualmente o guard por variável, sozinho, não equivale a aprovação efetiva.

## Histórico da retirada do legado

Os plans aprovados removeram os Ingresses/recursos Kong antigos e a release Helm que possuía o Service `LoadBalancer` responsável pelo NLB. O ALB interno, HTTP API, VPC Link, EKS, Lambda, RDS, Services internos, Deployments, NodePorts 30080/30081 e states dos outros componentes foram preservados no checkpoint.

Helm não remove automaticamente CRDs durante `helm uninstall`. No ambiente homologado, as CRDs foram verificadas sem objetos customizados e removidas; a instalação acadêmica separada também foi desinstalada. A consulta posterior não encontrou recursos AWS residuais exclusivos do Kong nem regras candidatas. Em outra conta, repetir inventário e aprovação antes de qualquer limpeza.

Não aplicar plans de destruição antes da aprovação. A ordem e os comandos de revisão estão no [runbook](runbook.md) e as evidências do checkpoint em [progresso](progresso.md).
