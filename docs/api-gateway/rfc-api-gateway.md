# RFC técnica — Entrada do AutoFlow com Amazon API Gateway

- **Data:** 13/10/2026
- **Estado:** arquitetura e configuração Terraform declaradas nos checkouts; implantação AWS não verificada nesta revisão.
- **Escopo:** HTTP API, autenticação Lambda, acesso privado ao EKS/RDS, operação Terraform e CI/CD deste repositório.

## Resumo

A arquitetura usa HTTP API v2 como endpoint HTTPS. Login chama a Lambda de autenticação por integração nativa. Frontend e API de negócio são encaminhados por VPC Link v2 a um ALB interno e daí a serviços no EKS. O Terraform configura RDS PostgreSQL privado. O desenho está em [`arquitetura.md`](arquitetura.md).

## Contratos e componentes

- Login: `POST /auth/login`, JSON `cpf_cnpj` e `senha`, `AWS_PROXY`, payload `2.0`; a permissão Lambda restringe principal, conta e ARN da rota.
- Login verifica credenciais e status aplicável no PostgreSQL; sucesso emite JWT HS256. O segredo JWT deve corresponder entre Lambda e backend.
- Rotas de backend usam integrações `HTTP_PROXY`, VPC Link e listener backend; rotas de frontend usam integração HTTP pelo mesmo VPC Link e listener frontend. O catálogo executável de rotas é `infra/api-gateway/routes.tf`.
- ALB interno encaminha a NodePorts 30081 (Spring Boot) e 30080 (Nginx/Angular). RDS não é público.
- O Spring Boot valida JWT e carrega perfil/estado para autorização; claims isolados não concedem acesso.

## Rede, segurança e observabilidade

O Security Group do ALB aceita tráfego dos ENIs do VPC Link nos listeners e encaminha aos nós nas portas NodePort; os NodePorts aceitam o SG do ALB. O tráfego VPC Link–ALB é HTTP e TLS termina no endpoint gerenciado do API Gateway, conforme configuração documentada. A HTTP API configura CORS por allowlist, throttling geral e específico para login, access logs sem dados de requisição sensíveis e alarmes de 5xx/targets sem hosts saudáveis.

## Terraform, ownership e implantação

O root `infra/api-gateway` consome outputs do state de EKS e consulta EKS, node group e função Lambda existentes. Mantém state S3 próprio com lockfile. Não compartilhe nem edite states manualmente. A sequência de dependências, variáveis genéricas, checks e limites de recuperação estão em [`runbook.md`](runbook.md). Não executar destroy global nem aplicar plano não revisado.

## CI/CD

CI ocorre em PRs e pushes conforme os workflows. Para `Pipeline` de VPC/EKS, primeiro configure `homolog`/`production` e valide a matriz externa das seis State Keys. O bootstrap do bucket é um `workflow_dispatch` independente autorizado por `approve_state_bucket_creation=true`; não inicia `validate`, Plan, Apply nem Terraform init. Após confirmar o bucket, faça dispatch separado para Plan e, após revisar o Plan, outro dispatch com `apply=true`; o Apply aguarda os gates e usa o Plan criptografado e vinculado à execução. O bootstrap e esses gates descrevem código versionado, não comprovam que os Environments ou recursos AWS estejam efetivamente configurados/implantados. Consulte o [procedimento de bootstrap](../state-bucket-bootstrap.md) e o [runbook](runbook.md).

## Escopo e limites

Esta RFC registra decisões e configuração de arquitetura. Os parâmetros de conta, região, state e credenciais são fornecidos à pipeline pelo ambiente de provisionamento. Procedimentos estão no [`runbook.md`](runbook.md).

Os artefatos consultados não registram comparação formal entre provedores de nuvem nem os decisores da escolha original. Esta RFC descreve a arquitetura AWS versionada, sem atribuir ao projeto uma análise histórica que não está documentada.
