# RFC técnica — Entrada do AutoFlow com Amazon API Gateway

- **Data:** 13/10/2026
- **Estado:** configuração Terraform declarada e homologada somente no ambiente AWS Academy Learner Lab documentado; nenhuma implantação em produção é declarada e reprodução em outra conta não presumida.
- **Escopo:** HTTP API, autenticação Lambda, acesso privado ao EKS/RDS, operação Terraform e CI/CD deste repositório.

## Resumo

A solução usa HTTP API v2 como endpoint HTTPS. Login chama a Lambda de autenticação por integração nativa. Frontend e API de negócio são encaminhados por VPC Link v2 a um ALB interno e daí a serviços no EKS. RDS PostgreSQL permanece privado. A arquitetura e evidências estão detalhadas em [`arquitetura.md`](arquitetura.md) e [`progresso.md`](progresso.md).

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

O checkpoint de 13/10/2026 registra HTTP API com 79 rotas/48 integrações, VPC Link disponível, ALB interno, dois targets saudáveis por grupo, EKS 2/2 nós, backend/frontend prontos, RDS disponível, 47 migrations e smokes positivos/negativos. A validação positiva posterior ao fechamento da Function URL está registrada. Não há comprovação de reprodução em segunda conta nem de configuração atual dos approvals GitHub.

## Não objetivos e lacunas

Esta RFC não declara requisito oficial além do que consta na fonte disponível, nem garante custos, capacidade, SLO, recuperação automatizada ou deploy contínuo. Os nomes/valores específicos do ambiente homologado não são parâmetros para copiar; devem ser obtidos na conta de destino. Consultar também a matriz de pendências em [`progresso.md`](progresso.md).
