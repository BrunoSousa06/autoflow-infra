# HTTP API do AutoFlow

Gateway de entrada definitivo do AutoFlow: HTTP API v2, integração nativa Lambda, VPC Link v2 e ALB **interno** para backend e frontend no EKS.

O root está configurado para provisionar HTTP API, VPC Link e ALB interno. Após reset do Learner Lab, execute novamente a pipeline Migração HTTP API para provisionar os recursos.

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

O backend S3 é parcial. Configure bucket, região e a key exclusiva por meio das Variables do GitHub Environment selecionado. A key deve começar por `homolog/` ou `production/`; o sufixo é fornecido externamente e não é decidido pelo código. `expected_account_id`, `terraform_state_bucket`, `infra_state_key` e `lambda_function_name` são obrigatórios. O backend recebe `expected_bucket_owner`. O `terraform_remote_state` embutido no Terraform 1.16.5 não aceita esse atributo; antes do init, o workflow verifica o objeto remoto com `head-object --expected-bucket-owner` usando a mesma conta esperada.

Quando aplicado, este root publica o endpoint pelo output `gateway_url`. Antes de qualquer Apply futuro, confirmar conta, state e escopo integral do plan; não aplicar planos de destruição sem aprovação específica.
