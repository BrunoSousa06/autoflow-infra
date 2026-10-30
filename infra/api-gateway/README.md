# HTTP API do AutoFlow

Gateway de entrada definitivo do AutoFlow: HTTP API v2, integração nativa Lambda, VPC Link v2 e ALB **interno** para backend e frontend no EKS.

O root declara HTTP API, VPC Link e ALB interno. Após reset do Learner Lab, configure os GitHub Environments, valide as State Keys, execute o bootstrap S3 isolado quando necessário e só então use a pipeline Migração HTTP API depois das dependências. Essas declarações não comprovam recursos atualmente implantados.

Os documentos ficam em `autoflow-infra/docs/api-gateway/`, a partir da raiz do repositório:

- [Arquitetura e diagramas C4](../../docs/api-gateway/arquitetura.md)
- [ADR-001 — substituição Kong → API Gateway](../../docs/api-gateway/adr-001-api-gateway.md)
- [RFC técnica](../../docs/api-gateway/rfc-api-gateway.md)
- [Runbook: Learner Lab, implantação, smoke, recuperação e rollback](../../docs/api-gateway/runbook.md)

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

Quando aplicado, este root publica o endpoint pelo output `gateway_url`. Antes de qualquer Apply futuro, confirmar conta, state e escopo integral do plan; não aplicar planos de destruição sem aprovação específica.
