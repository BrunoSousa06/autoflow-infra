# Bootstrap do bucket Terraform State

## Sequência operacional

1. **Configurar e auditar os GitHub Environments.** `develop` usa `homolog`; `main` usa `production`. Em cada Environment, cadastre `AWS_EXPECTED_ACCOUNT_ID`, `AWS_REGION`, `AWS_TERRAFORM_STATE_BUCKET` e os Secrets temporários `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_SESSION_TOKEN`. Uma identidade administrativa autorizada deve confirmar Required reviewers e branch policies fora da pipeline; só então cadastre `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`. Os valores de conta, região, bucket e credenciais devem pertencer ao Environment selecionado e à mesma conta AWS Academy Learner Lab. Consulte a [auditoria administrativa externa](github-runner.md#auditoria-administrativa-externa).

2. **Validar o contrato dos seis States.** Prepare fora do checkout o JSON de configuração dos roots `vpc_eks`, `rds`, `lambda`, `application`, `api_gateway` e `newrelic` para `homolog` e `production`, com conta, bucket, região, keys e relações `consumes`. Execute `python scripts/terraform_state_contract.py <caminho-externo-para-configuracao.json>`. Essa validação é local, não acessa AWS, não inicializa backend nem prova que os objetos ou States existem; ela verifica prefixos por ambiente, unicidade das keys e consistência produtor/consumidor. A lista de Variables por root está em [`arquitetura.md`](api-gateway/arquitetura.md#states-e-ownership).

3. **Executar o bootstrap isolado.** No workflow `Pipeline`, `workflow_dispatch` em `develop` ou `main` com `approve_state_bucket_creation=true` seleciona o job `bootstrap_state_bucket`. `main` também precisa estar protegida. O job não tem dependências (`needs`) e os jobs `validate`, `plan` e `apply` têm condições que os fazem ignorar esse dispatch. Nenhum outro workflow é chamado por esse evento.

4. **Verificar bucket e controles.** O job aguarda a aprovação nativa do GitHub Environment selecionado. Antes de configurar credenciais AWS, valida que os valores não estão vazios, que conta e região têm formato válido, que `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true` e que a identidade corresponde ao Environment selecionado. A pipeline não consulta APIs administrativas de Variables, Secrets ou reviewers. Em seguida, `sts:GetCallerIdentity` precisa corresponder a `AWS_EXPECTED_ACCOUNT_ID`; o script também repete a validação STS antes das chamadas S3. O nome do bucket é exclusivamente `AWS_TERRAFORM_STATE_BUCKET`.

5. **Executar Terraform posteriormente.** Depois do sucesso do bootstrap e da revisão do resultado, faça um dispatch separado sem autorização de criação. `apply=false` executa Plan para inspeção; `apply=true` executa Plan e só aplica o mesmo artifact após os gates de proteção, fingerprint, integridade, conta e Environment. Plans criptografados, validações de state e os demais guards existentes permanecem obrigatórios.

## Autorização e flags

| Nome | Finalidade atual | Estado durante o bootstrap |
|---|---|---|
| `approve_state_bucket_creation` | Input booleano de `workflow_dispatch`; `true` seleciona o job isolado e autoriza criação somente se o bucket estiver ausente. | `true` — única autorização explícita de operação do bootstrap. |
| `apply` | Input booleano que habilita Apply no fluxo Terraform. | `false`; mesmo se enviado como `true`, o Apply é bloqueado quando o input de bootstrap está `true`. |
| `approve_eks_state_reconciliation` | Autoriza reconciliações delimitadas do State/acesso EKS. | `false`; não é necessário para o bucket. |
| `allow_destructive` | Autoriza ações destrutivas depois da revisão do Plan. | `false`; não é necessário para o bucket. |
| `APPROVE_CREATE` | Variable legada anteriormente usada pelo fluxo inline. | Não é lida pelo workflow atual; não configura nem substitui o input de dispatch. |
| `TERRAFORM_APPLY_APPROVAL_CONFIGURED` | Marcador de configuração que precisa ser `true` somente depois da auditoria externa dos Required reviewers e da branch policy no Environment. | `true` como precondição adicional; não substitui a aprovação nativa nem cria Required reviewers. |

## Chamadas de workflow para uso futuro

Os comandos abaixo são exemplos documentais e **não foram executados**. Para homologação:

```bash
gh workflow run pipeline.yml --ref develop \
  -F apply=false \
  -F approve_state_bucket_creation=true \
  -F approve_eks_state_reconciliation=false \
  -F allow_destructive=false
```

Para produção, selecione `main`; a branch precisa estar protegida e o Environment `production` precisa exigir Required reviewers:

```bash
gh workflow run pipeline.yml --ref main \
  -F apply=false \
  -F approve_state_bucket_creation=true \
  -F approve_eks_state_reconciliation=false \
  -F allow_destructive=false
```

Para um Plan posterior, faça um novo dispatch com `approve_state_bucket_creation=false` e `apply=false`. Para Apply, faça outro dispatch com `approve_state_bucket_creation=false` e `apply=true`; o run gera um Plan novo, protegido e vinculado à execução, e aguarda a aprovação do Environment antes de aplicá-lo.

## Controles, falhas e recuperação

- Bucket ausente com autorização: cria o bucket na região selecionada, configura os controles abaixo e lê a configuração de volta. O job nunca copia, lê, altera ou exclui objetos de State.
- Bucket existente e compatível: operação idempotente e somente leitura; não executa `put-*` nem `create-bucket`.
- Bucket existente com proprietário incorreto, erro `AccessDenied`, erro de rede ou resposta ambígua: falha fechada; não classifica como ausência e não tenta criar outro bucket.
- Bucket existente incompatível: falha sem corrigir controles. A correção deve ser analisada e autorizada separadamente; não use o Plan para fazer bootstrap.
- Se uma criação nova for seguida por falha ao aplicar/verificar algum controle, o bucket pode permanecer parcialmente configurado. Pare a sequência, preserve-o para inspeção e corrija a configuração sob procedimento autorizado; não o exclua nem inicie Terraform.
- Se o bootstrap falhar, não execute Plan/Apply. Revise a causa, corrija apenas a configuração aprovada e repita o job isolado quando todas as precondições estiverem atendidas.
- **Recuperação do HTTP 403 antigo (`Resource not accessible by integration`).** Esse erro vinha das consultas à API administrativa de Environments com `GITHUB_TOKEN` nos preflights de bootstrap, Plan ou Apply. Elas ocorriam antes de configurar credenciais AWS e antes de chamadas AWS; não amplie permissões nem adicione PAT. Atualize para os workflows que validam os valores injetados por `vars`/`secrets`, confirme os valores necessários no Environment selecionado e peça a uma identidade administrativa autorizada para executar a auditoria externa documentada em [github-runner.md](github-runner.md#auditoria-administrativa-externa). Confirme Required reviewers e branch policies antes de manter `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`. Depois da revisão, repita somente o dispatch isolado de bootstrap (`approve_state_bucket_creation=true`, com `apply`, `approve_eks_state_reconciliation` e `allow_destructive` em `false`). Se esse job tiver concluído, faça Plan/Apply em dispatches separados conforme o fluxo normal.

Os controles exigidos são: `BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy` e `RestrictPublicBuckets` verdadeiros; versionamento `Enabled`; criptografia default AES256 sem regra restrita a prefixo; proprietário igual a `AWS_EXPECTED_ACCOUNT_ID`.

Nenhum resultado local comprova estado AWS implantado. O script é testado com mocks; o bucket real só é verificado quando o operador executar o workflow após revisão.

## Validação local

Os testes usam mocks e não acessam AWS:

```bash
python -m unittest discover -s scripts -p 'test_bootstrap_state_bucket.py' -v
python -m unittest discover -s scripts -p 'test_bootstrap_workflow_isolation.py' -v
```
