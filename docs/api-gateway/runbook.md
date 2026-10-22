# Runbook do gateway e retirada do legado

## Topologia operacional

Entrada pública HTTPS: Amazon API Gateway HTTP API. Login `POST /auth/login` integra nativamente com Lambda (`AWS_PROXY`, payload `2.0`). As demais rotas seguem pelo VPC Link, ALB interno e NodePorts privados no EKS. RDS PostgreSQL permanece privado. Frontend, backend, NodePorts e API Gateway foram homologados em 13/10/2026; consulte o [checkpoint](progresso.md).

Os identificadores acima são evidência histórica do ambiente homologado, não valores reutilizáveis. Para reproduzir, use outputs, nomes e variáveis da conta de destino; não copie IDs, ARNs, endpoints ou credenciais deste documento.

## AWS Academy Learner Lab

1. Iniciar o Learner Lab e renovar a sessão/credenciais temporárias; configurar `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_SESSION_TOKEN` apenas no ambiente seguro. Não persistir tokens em arquivos versionados.
2. Definir perfil (quando aplicável), região e `AWS_EXPECTED_ACCOUNT_ID`; validar `aws sts get-caller-identity` e executar `scripts/verify_aws_account.py` antes de qualquer operação.
3. Conferir limites/cotas e disponibilidade dos serviços exigidos na região da conta. O laboratório pode suspender recursos/sessões; não presumir que endpoints ou credenciais persistam.
4. Confirmar acesso ao bucket S3, keys e states autoritativos. Renovar credenciais expiradas e repetir o preflight; não contornar erros de sessão inicializando state alternativo.
5. Usar as variáveis protegidas do workflow e o environment `homolog`. Required reviewers precisam estar configurados no próprio GitHub; uma variável declarativa sozinha não comprova aprovação efetiva.

## States Terraform e reprodução em outra conta

Cada componente mantém state remoto independente: plataforma/EKS, aplicação, RDS, Lambda e API Gateway. Em uma conta de destino, inventarie primeiro os recursos e determine se são novos ou preexistentes; registre ownership e associe o state correto. Configure bucket S3, região, key exclusiva por root, criptografia e lockfile conforme políticas da conta. Configure backend e `TF_VAR_*` com valores daquele ambiente, inclusive conta esperada, cluster/node group, função Lambda, CORS, alarm actions e referências dos states consumidos. Segredos de banco/JWT devem ser fornecidos por mecanismo protegido.

Não use os states do Learner Lab em outra conta, não inicialize state vazio sobre recursos existentes, não copie state/plan e não execute `state rm` para forçar adoção. Se recursos já existirem sem state correspondente, interrompa a implantação e planeje importação/adopção separadamente, com inventário e revisão. Execute `fmt`, `init -backend=false`, `validate` e testes; em seguida configure backend remoto e faça plan. Compare todas as ações e confirme a conta antes de qualquer Apply aprovado. A reprodução em outra conta ainda não foi homologada.

Ordem de dependências recomendada pelos roots Terraform: VPC/EKS e rede → RDS/conectividade → Lambda e configuração segura → aplicação no EKS → API Gateway/VPC Link/ALB → smoke ponta a ponta. Confirme a disponibilidade real das dependências antes de cada etapa; não aplique root sem seus states/outputs requeridos.

## Smoke tests

Após implantação ou alteração aprovada, validar sem registrar credenciais ou tokens:

1. VPC Link `AVAILABLE`, ALB `internal/active`, listener/Target Groups associados e targets saudáveis.
2. API Gateway stage/rotas e integração login; frontend responde HTTP 200, assets essenciais e deep links carregam.
3. Login com fixture autorizada do ambiente: sucesso HTTP 200 e JWT emitido. Não imprimir corpo, senha ou token.
4. Chamada autenticada a uma rota protegida: HTTP 200 para identidade autorizada; credencial inválida/inativa e rota sem autorização devem ser recusadas conforme contrato.
5. Verificar logs/alarmes sem expor dados pessoais, JWT ou segredos; confirmar conectividade ao RDS pelo health check da aplicação.

Os códigos e resultados homologados em 13/10/2026 estão no checkpoint. Executar os smokes de novo na conta destino; os resultados históricos não os substituem.

## Recuperação e rollback

- **Falha de sessão/permissão:** parar; renovar credenciais, confirmar conta/região e permissões mínimas e repetir preflight. Não alterar state nem trocar de conta para prosseguir.
- **Plan inesperado ou divergente:** não aplicar. Atualizar inventário, state e plan; solicitar nova revisão/aprovação. Não aplicar plan antigo após mudança de state ou expiração de sessão.
- **Falha em rota/login:** consultar access logs do API Gateway, logs da Lambda e backend e health dos Target Groups; correlacionar por request ID. Não habilitar logs de body/token. Corrigir a causa e gerar novo plan quando houver alteração Terraform.
- **Regressão após Apply:** interromper novos Applies; preservar logs/plan, avaliar reversão por alteração declarativa e novo plan aprovado. Reverter configuração da aplicação separadamente quando pertinente. Não presumir rollback automático de dados/migrations.
- **Retorno ao Kong:** não é fallback automático. Requer plano explícito de reimplantação, validação de compatibilidade e aprovação; não recriar Function URL pública.
- Nunca executar `terraform destroy` global, editar state manualmente ou remover recursos compartilhados como tentativa de recuperação.

## Preparação e operação normal

- Confirmar conta/região/perfil AWS e state S3 autoritativo de cada componente antes de Terraform.
- `autoflow-infra/infra/api-gateway` gerencia API, rotas, integração Lambda, VPC Link, ALB, Target Groups, SGs e alarmes.
- `autoflow/infra` gerencia ConfigMaps, Deployments, Services internos e NodePorts `30080/30081`.
- `autoflow-lambda/infra` mantém a função Lambda. A Function URL legada e suas permissões públicas foram removidas no ambiente homologado; a permissão nativa do API Gateway permanece.
- `autoflow-db/infra` gerencia somente recursos do banco.
- Não publicar Secrets, credentials, Terraform states/plans ou tokens. Planos binários permanecem locais e ignorados pelo Git.

## Status dos Plans de teardown

Os artefatos Terraform são locais e ignorados pelo Git. Os teardowns principais foram regenerados contra os states atuais, revisados sem drift e aplicados com os escopos abaixo. Nenhum outro recurso foi removido.

### 1. Fechar a Function URL pública

O Plan `autoflow-lambda/infra/function-url-close-review.tfplan` foi aplicado após preflight e autorização: **0 add / 0 change / 3 destroy** (Function URL e duas permissões públicas). A URL não existe mais. A permissão de invocação `AllowAutoflowHttpApiLogin` permanece no root `autoflow-infra/infra/api-gateway`. O arquivo `function-url-close-minimal.tfplan` é obsoleto; não aplicar nenhum dos dois novamente.

Validação após o Apply: Function URL ausente, dois statements públicos removidos, permissão API Gateway presente e integração nativa payload v2. Smoke pós-teardown confirmou login positivo HTTP 200, JWT aceito pela API protegida HTTP 200 e frontend HTTP 200.

### 2. Remover referências Kubernetes do gateway antigo

Plan revalidado e aplicado em `autoflow/infra`: **0 add / 0 change / 11 destroy** — 9 Ingresses, 1 KongPlugin e 1 Service ExternalName da URL. Deployment, frontend, backend, Services internos, ConfigMap do API Gateway e NodePorts 30080/30081 permaneceram funcionais.

### 3. Remover release principal e NLB

Plan revalidado e aplicado em `autoflow-infra/infra/kong`: **0 add / 0 change / 1 destroy**, somente `helm_release.kong`. O Service `kong-kong-proxy`, o NLB e os Target Groups associados foram removidos pelo controlador. API Gateway, VPC Link `AVAILABLE`, ALB interno, EKS e RDS permaneceram funcionais.

Não executar um `terraform destroy` global. Os dois Plans principais foram aplicados com escopo validado. Na execução posterior da limpeza residual foram removidos, sob autorização, a release acadêmica, 12 CRDs vazias, o Secret TLS e o namespace `kong`. Nenhuma regra de Security Group foi alterada. A `IngressClass kong` havia desaparecido como efeito da desinstalação Helm principal.

## Resíduos Kubernetes fora dos Plans principais

Helm não remove CRDs na desinstalação. As 12 CRDs `configuration.konghq.com` listadas abaixo foram reconsultadas em todos os namespaces, confirmadas sem custom resources e removidas explicitamente. A `IngressClass kong` está ausente como efeito da remoção da release principal e não foi recriada.

O release `autoflow-kong-academic` não constava nos states Terraform. Foi removido por `helm uninstall autoflow-kong-academic --namespace autoflow-auth-demo --wait`. Foram removidos seus Service/Deployment/ConfigMap/ServiceAccount, ReplicaSet/Pod dependentes e Secret de histórico Helm; a verificação pós-operação encontrou zero Pods, Deployments ou Services da release. A namespace `autoflow-auth-demo` foi preservada com `kube-root-ca.crt` e ServiceAccount `default`.

Consulta AWS após a remoção não encontrou NLB, Target Groups, ENIs ou regras SG identificadas pelo ownership/nome/portas do Kong antigo. Nenhuma regra foi alterada. Preservar as regras `30080/30081` usadas pelo caminho ALB/API Gateway.

### CRDs Kong removidas após validação de dependências

O inventário atual encontrou 12 CRDs Kong:

```text
ingressclassparameterses.configuration.konghq.com
kongclusterplugins.configuration.konghq.com
kongconsumergroups.configuration.konghq.com
kongconsumers.configuration.konghq.com
kongcustomentities.configuration.konghq.com
kongingresses.configuration.konghq.com
konglicenses.configuration.konghq.com
kongplugins.configuration.konghq.com
kongupstreampolicies.configuration.konghq.com
kongvaults.configuration.konghq.com
tcpingresses.configuration.konghq.com
udpingresses.configuration.konghq.com
```

O `KongPlugin` `default/autoflow-reserved-paths-404` foi removido pelo Plan de 11 exclusões. Cada uma das 12 CRDs acima foi consultada em todos os namespaces e tinha zero custom resources antes da exclusão; todas foram removidas. A `IngressClass kong` permanece ausente; não recriar sem aprovação.

O release acadêmico foi removido conforme o procedimento acima. Não restaram Pods, Deployments ou Services associados.

O Secret `kong-homolog-tls` não tinha consumidores em Pods, Deployments, StatefulSets, DaemonSets, Jobs ou CronJobs e foi removido. O namespace `kong` continha somente o Secret, `kube-root-ca.crt`, ServiceAccount `default` e eventos históricos, sem workloads nem referências em ClusterRoleBindings, webhooks ou APIServices; o Secret foi removido e o namespace foi excluído. A namespace `autoflow-auth-demo` foi mantida.

Não há regras candidatas ao Kong antigo no inventário atual. Não excluir Security Groups nem regras de portas `30080/30081` referenciadas pelo ALB.

## Verificação pós-limpeza

1. Os Target Groups do ALB permanecem `healthy`; VPC Link `AVAILABLE`; ALB `internal/active`.
2. API Gateway mantém rotas, integração Lambda nativa e sucesso de login/JWT/consulta protegida.
3. NLB e Target Groups associados ao Service antigo desapareceram; regras SG residuais devem ser apenas inspecionadas por ID/ownership, sem remoção manual nesta operação.
4. EKS, ALB, API Gateway, RDS, Deployments, Services internos e NodePorts privados permanecem presentes. Não há releases/CRDs/IngressClass/Services/Pods ativos exclusivos do Kong.
5. Smoke final: login, JWT e consulta autenticada HTTP 200; frontend HTTP 200; 12 assets e 3 deep links aprovados. Cada Target Group do ALB tem 2/2 targets `healthy`.

## Rollback e limites

Antes da limpeza Kong, o API Gateway é o caminho funcional homologado. Se o fechamento da URL falhar, reparar a integração nativa; não reabrir `NONE` automaticamente. Após remover Ingresses/Helm, a restauração do Kong exigiria reimplantação explícita e nova aprovação; não é um fallback automático.

Em outra conta, qualquer exclusão residual exige aprovação específica, validação imediata de ownership e ausência de dependentes. Não editar states manualmente e não fazer commit/push.
