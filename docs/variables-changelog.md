# Histórico de variables e secrets

## 2026-10-14 — Registro histórico do catálogo

- Inventário inicial baseado nos workflows e inputs Terraform observados naquela revisão.
- Nenhum changelog anterior de variables/secrets foi localizado; alterações históricas anteriores não são inferidas.
- Naquele snapshot, somente `homolog` era documentado como ambiente de deploy; produção permanecia planejada.

## 2026-10-30 — Bootstrap S3 isolado e ambientes declarados

- `approve_state_bucket_creation` seleciona, por `workflow_dispatch`, um job independente limitado a `develop`/`homolog` e `main`/`production`; o dispatch pula `validate`, Plan e Apply.
- `APPROVE_CREATE` deixou de ser consumida. `TERRAFORM_APPLY_APPROVAL_CONFIGURED` permanece como marcador de proteção e não substitui Required reviewers efetivos do Environment.
- O job usa `AWS_EXPECTED_ACCOUNT_ID`, `AWS_REGION`, `AWS_TERRAFORM_STATE_BUCKET` e os três Secrets AWS do Environment selecionado. O Plan comum apenas verifica bucket, proprietário e controles.
- README, arquitetura e runbooks agora descrevem as seis State Keys e a validação local da matriz; sufixos reais permanecem fornecidos pelos Environments e não são versionados.
- Alterações e testes são locais. Nenhuma Environment, Variable, Secret ou configuração/recurso AWS foi consultado ou alterado nesta documentação; execução AWS permanece não verificada.
