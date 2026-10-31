# HTTP API do AutoFlow

Gateway de entrada definitivo do AutoFlow: HTTP API v2, integração nativa Lambda, VPC Link v2 e ALB **interno** para backend e frontend no EKS.

O root declara HTTP API, VPC Link e ALB interno. A pipeline `Migração HTTP API` consome os GitHub Environments e os
States de VPC/EKS; o bootstrap S3 isolado deve ser executado quando o bucket ainda não existir.

Os documentos ficam em `autoflow-infra/docs/api-gateway/`, a partir da raiz do repositório:

- [Arquitetura e diagramas C4](../../docs/api-gateway/arquitetura.md)
- [ADR-001 — API Gateway HTTP API v2](../../docs/api-gateway/adr-001-api-gateway.md)
- [RFC técnica](../../docs/api-gateway/rfc-api-gateway.md)
- [Runbook de implantação, validação e recuperação](../../docs/api-gateway/runbook.md)

## Uso local

Execute neste diretório, com Terraform >= 1.10 e credenciais temporárias válidas:

```powershell
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate
terraform test
terraform -chdir=modules/private-eks init -backend=false -input=false
terraform -chdir=modules/private-eks test
```

O backend S3 é parcial e este root não cria o bucket. Configure bucket, região e a key exclusiva por meio das Variables do GitHub Environment selecionado. A key deve começar por `homolog/` ou `production/`; o sufixo é fornecido externamente e não é decidido pelo código. `expected_account_id`, `terraform_state_bucket`, `infra_state_key` e `lambda_function_name` são obrigatórios. Se o bucket estiver ausente, use primeiro o [bootstrap isolado](../../docs/state-bucket-bootstrap.md); não use este workflow para criá-lo. O `terraform init` recebe `allowed_account_ids` usando `TF_VAR_aws_allowed_account_ids`, derivado da variável externa `AWS_EXPECTED_ACCOUNT_ID`; o `terraform_remote_state` usa o mesmo ID. `encrypt=true` e `use_lockfile=true` são obrigatórios. Antes do init, o workflow verifica o objeto remoto com AWS CLI `head-object --expected-bucket-owner` usando a mesma conta esperada.

Para validar a configuração local sem AWS, execute `terraform init -backend=false -input=false`, `terraform validate` e `python -m unittest discover -s scripts -p "test_terraform_backend_config.py" -v` na raiz do repositório. Para um init remoto autorizado, use somente o bucket/key aprovados e a configuração externa de conta, mantendo os mesmos argumentos de criptografia e locking descritos no workflow.

## Observabilidade declarada

O root configura access logs JSON no CloudWatch com `requestId`, template de rota, status HTTP, latência e status de
integração; não registra IP, query, body ou headers. O log group retém eventos por sete dias. Há alarmes CloudWatch para
respostas 5xx e ausência de targets saudáveis no ALB. `alarm_actions` é vazio por padrão, portanto não declara destino de
notificação; métricas detalhadas por rota também ficam desativadas por padrão e exigem habilitação externa.

O dashboard opcional de API Gateway no New Relic recebe consultas NRQL por Environment, fornecidas por
`NEW_RELIC_API_GATEWAY_DASHBOARD_QUERIES_JSON` no root New Relic.

Após Apply, o output `gateway_url` retorna o endpoint da API configurada. Antes de Apply, revise conta, State e o Plan
completo; mudanças destrutivas exigem autorização específica.
