# Runbook do API Gateway

> A configuração está finalizada e provisionável pelas pipelines CI/CD. Após reset do AWS Academy Learner Lab, reexecute as pipelines na ordem abaixo.

## Topologia

O Amazon API Gateway HTTP API v2 recebe tráfego HTTPS. `POST /auth/login` invoca a Lambda pela integração `AWS_PROXY`, payload `2.0`. Frontend e rotas de negócio seguem por VPC Link e ALB interno até os NodePorts `30080` (Nginx/Angular) e `30081` (Spring Boot) no EKS. Lambda e backend acessam o RDS PostgreSQL privado. A Function URL não faz parte do fluxo configurado.

## Provisionamento

Antes de iniciar, confirme a sessão AWS, conta, região, variáveis e Secrets requeridos pelos workflows. Preserve os states remotos existentes: cada root usa state independente; não inicialize state vazio sobre recursos existentes nem edite state manualmente.

Execute as pipelines nesta ordem:

1. `autoflow-infra`: VPC, rede, EKS e node group (`Pipeline`).
2. `autoflow-db`: RDS PostgreSQL e rede privada.
3. `autoflow-lambda`: função de autenticação e configuração de execução.
4. `autoflow-infra`: HTTP API, VPC Link e ALB (`Migração HTTP API`).
5. `autoflow`: aplicação, Services e NodePorts no EKS.
6. `autoflow-infra`: integração New Relic, após a aplicação e seus Secrets estarem provisionados.

Revise integralmente cada Terraform Plan. Interrompa diante de conta/região/state inesperados, drift não explicado, substituições ou destruições fora do escopo. Execute Apply somente pela pipeline aprovada; não use `terraform destroy` global nem reutilize plans antigos após alteração de state.

## Verificação após provisionamento

1. Confirme VPC Link disponível, ALB interno ativo e targets dos NodePorts saudáveis.
2. Confirme frontend e assets, login com fixture sintética autorizada e resposta JWT sem registrar senha ou token.
3. Use o JWT em uma rota protegida; verifique também health do backend e conectividade ao RDS.
4. Confirme logs e telemetria sem expor dados pessoais, bodies, tokens ou Secrets.

## Recuperação

- Em falha de sessão, conta ou permissão, interrompa o fluxo, renove as credenciais e repita o preflight.
- Em Plan inesperado ou falha de provisionamento, não aplique novamente sem revisar a causa e gerar um novo Plan.
- Para falhas de login ou rota, correlacione logs do API Gateway, Lambda e backend por request ID; não habilite log de payload ou token.
- Mudanças e rollback devem ser feitos por configuração declarativa e pipeline; não altere state manualmente nem reintroduza Kong ou Function URL.
