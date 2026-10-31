# Runners GitHub-hosted e acesso ao EKS

Os workflows usam runners GitHub-hosted `ubuntu-latest`; os roots Terraform não provisionam runner dedicado.

## Acesso temporário ao endpoint

Os workflows de VPC/EKS e New Relic selecionam o cluster do Environment, obtêm o IPv4 público do job e autorizam
temporariamente esse endereço como `/32` no endpoint EKS. `scripts/eks_endpoint_access.py` registra a autorização em
lease S3, serializa operações concorrentes, reconcilia leases anteriores e remove a regra temporária ao final do job.
Os CIDRs permanentes são preservados; o workflow não permite `0.0.0.0/0`.

O endpoint privado do cluster permanece habilitado. A saída pública deve manter apenas CIDRs permanentes autorizados e o
endereço temporário do runner. O bucket e as permissões S3 para o lease são pré-requisitos dos workflows que acessam o
cluster.

## Plan, Apply e configuração do GitHub

O Plan é criptografado e vinculado a checksum, fingerprint, commit e execução. Apply reutiliza o artifact do mesmo run e
aplica o Plan após validação. Os jobs usam o GitHub Environment selecionado; configure Required reviewers e restrinja
`homolog` a `develop` e `production` a `main`. Em produção, a branch `main` também precisa estar protegida.

O bootstrap do bucket é um job separado em `workflow_dispatch` com `approve_state_bucket_creation=true`; o dispatch não
executa validação Terraform, Plan, Apply ou `terraform init`. Os comandos e inputs estão no
[runbook do bucket](state-bucket-bootstrap.md). Configure as Variables e Secrets de cada Environment conforme o
[catálogo](variables-and-secrets.md).
