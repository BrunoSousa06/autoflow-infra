# Runbook do API Gateway

> Este runbook descreve configuração versionada e procedimentos declarados; não confirma implantação atual na AWS. Após reset, configure os GitHub Environments, valide as State Keys e execute o [bootstrap S3 isolado](../state-bucket-bootstrap.md) antes de qualquer Terraform init ou pipeline de root.

## Topologia

O Amazon API Gateway HTTP API v2 recebe tráfego HTTPS. `POST /auth/login` invoca a Lambda pela integração `AWS_PROXY`, payload `2.0`. Frontend e rotas de negócio seguem por VPC Link e ALB interno até os NodePorts `30080` (Nginx/Angular) e `30081` (Spring Boot) no EKS. Lambda e backend acessam o RDS PostgreSQL privado. A Function URL não faz parte do fluxo configurado.

## Provisionamento

Antes de iniciar, configure `homolog` para `develop` e `production` para `main`, incluindo Variables e Secrets próprios de cada Environment e Required reviewers efetivos. Audite os reviewers e branch policies com uma identidade administrativa autorizada antes de definir `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`; a pipeline não consulta APIs administrativas de Environment. Preencha a matriz das seis State Keys com os valores de conta/região esperados e valide-a com `python scripts/terraform_state_contract.py <caminho-externo-para-configuracao.json>`. O comando valida somente o contrato fornecido, não confirma a identidade AWS, não acessa AWS nem consulta States remotos; a identidade real é validada pelo job protegido. Para recuperação do HTTP 403 no preflight, siga o [runbook do bootstrap S3](../state-bucket-bootstrap.md#controles-falhas-e-recuperacao).

Antes de qualquer Terraform init, execute o [bootstrap S3 isolado](../state-bucket-bootstrap.md) quando o bucket estiver ausente ou precisar de verificação. O dispatch autorizado verifica identidade AWS e controles do bucket, sem inicializar Terraform ou acionar Plan/Apply. Faça depois um dispatch separado para VPC/EKS, revise o Plan criptografado e só então solicite Apply com os gates do Environment. Não use o input de bootstrap como autorização para provisionamento.

Preserve os States remotos existentes: cada root usa State independente; não inicialize State vazio sobre recursos existentes nem edite State manualmente. A tabela de seis roots, suas Variables de State Key e o limite de validação por checkout está em [arquitetura — States e ownership](arquitetura.md#states-e-ownership).

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
