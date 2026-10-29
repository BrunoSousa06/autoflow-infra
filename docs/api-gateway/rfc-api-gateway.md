# RFC técnica — Entrada do AutoFlow com Amazon API Gateway

- **Data:** 13/10/2026
- **Estado:** configuração declarada em Terraform. As evidências de homologação são anteriores ao reset do AWS Academy Learner Lab e não validam o estado atual; produção não é declarada como provisionada.
- **Escopo:** HTTP API, autenticação Lambda, acesso privado ao EKS/RDS, operação Terraform e CI/CD deste repositório.

## Resumo

A arquitetura declarada usa HTTP API v2 como endpoint HTTPS. Login chama a Lambda de autenticação por integração nativa. Frontend e API de negócio são encaminhados por VPC Link v2 a um ALB interno e daí a serviços no EKS. O Terraform declara RDS PostgreSQL privado. O desenho está em [`arquitetura.md`](arquitetura.md); a seção de evidência dessa página é explicitamente histórica.

## Contratos e componentes

- Login: `POST /auth/login`, JSON `cpf_cnpj` e `senha`, `AWS_PROXY`, payload `2.0`; a permissão Lambda restringe principal, conta e ARN da rota.
- Login verifica credenciais e status aplicável no PostgreSQL; sucesso emite JWT HS256. O segredo JWT deve corresponder entre Lambda e backend.
- Rotas de backend usam integrações `HTTP_PROXY`, VPC Link e listener backend; rotas de frontend usam integração HTTP pelo mesmo VPC Link e listener frontend. O catálogo executável de rotas é `infra/api-gateway/routes.tf`.
- ALB interno encaminha a NodePorts 30081 (Spring Boot) e 30080 (Nginx/Angular). RDS não é público.
- O Spring Boot valida JWT e carrega perfil/estado para autorização; claims isolados não concedem acesso.

## Rede, segurança e observabilidade

O Security Group do ALB aceita tráfego dos ENIs do VPC Link nos listeners e encaminha aos nós nas portas NodePort; os NodePorts aceitam o SG do ALB. O tráfego VPC Link–ALB é HTTP e TLS termina no endpoint gerenciado do API Gateway, conforme configuração documentada. A HTTP API configura CORS por allowlist, throttling geral e específico para login, access logs sem dados de requisição sensíveis e alarmes de 5xx/targets sem hosts saudáveis. Esses controles descrevem Terraform local; apenas os itens explicitamente listados no checkpoint foram verificados em runtime.

## Terraform, ownership e implantação

O root `infra/api-gateway` consome outputs do state de EKS e consulta EKS, node group e função Lambda existentes. Mantém state S3 próprio com lockfile. Não compartilhe nem edite states manualmente. A sequência de dependências, variáveis genéricas, checks e limites de recuperação estão em [`runbook.md`](runbook.md). Não executar destroy global nem aplicar plano não revisado.

## CI/CD

CI ocorre automaticamente em PRs e pushes para `develop` e `main`, conforme os workflows de cada repositório. CD só é iniciado por `workflow_dispatch` em `develop`, com destino ao Environment `homolog`. O workflow valida credenciais/conta e state, gera Terraform Plan e aplica gates de segurança; alterações destrutivas exigem input de autorização e revisão do plano. Apply depende de despacho explícito e de `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`. Isso é um guard do workflow, não evidência de Required reviewers configurados no GitHub Environment; aprovação efetiva permanece não verificada. Não há evidência de execução do CD pelo GitHub Actions. A configuração também não declara um segundo EKS/RDS ou CD de produção.

## Homologação registrada

O registro de 13/10/2026, anterior ao reset do Learner Lab, anotou HTTP API com 79 rotas/48 integrações, VPC Link disponível, ALB interno, dois targets saudáveis por grupo, EKS 2/2 nós, backend/frontend prontos, RDS disponível, 47 migrations e smokes positivos/negativos. É uma evidência histórica e não comprova recursos ativos agora. A reprodução após o reset, em outra conta e a configuração efetiva dos approvals GitHub permanecem não verificadas.

## Não objetivos e lacunas

Esta RFC não garante custos, capacidade, SLO, recuperação automatizada ou deploy contínuo. Os nomes/valores específicos da observação histórica não são parâmetros para copiar; devem ser obtidos na conta de destino. Procedimentos e verificações estão no [`runbook.md`](runbook.md).
