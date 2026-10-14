# HTTP API do AutoFlow

Gateway de entrada definitivo do AutoFlow: HTTP API v2, integração nativa Lambda, VPC Link v2 e ALB **interno** para backend e frontend no EKS.

**Estado em 13/10/2026:** HTTP API, VPC Link e ALB interno implantados; Function URL e runtime Kong removidos conforme checkpoint; smoke autenticado pós-limpeza registrado. Isso descreve o ambiente homologado, não garante o estado de outras contas.

Os documentos ficam em `autoflow-infra/docs/api-gateway/`, a partir da raiz do repositório:

- [Arquitetura e diagramas C4](../../docs/api-gateway/arquitetura.md)
- [ADR-001 — substituição Kong → API Gateway](../../docs/api-gateway/adr-001-api-gateway.md)
- [RFC técnica](../../docs/api-gateway/rfc-api-gateway.md)
- [Runbook: Learner Lab, implantação, smoke, recuperação e rollback](../../docs/api-gateway/runbook.md)
- [Evidências, progresso e checkpoint](../../docs/api-gateway/progresso.md)

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

O backend S3 é parcial. Configure bucket, região e a chave exclusiva `api-gateway/terraform.tfstate` conforme o runbook. `expected_account_id`, `terraform_state_bucket` e `lambda_function_name` são obrigatórios; não há conta ou bucket de laboratório embutidos no módulo. O provider utiliza o perfil/credenciais do processo.

O endpoint implantado é fornecido pelo output `gateway_url`. Antes de aplicar mudanças neste root, confirmar conta, state e escopo integral do plan salvo; não aplicar planos de destruição sem aprovação específica.
