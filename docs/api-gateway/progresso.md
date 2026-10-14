# Checkpoint da migração para Amazon API Gateway

## Pausa para continuidade — 13/10/2026

**Última tarefa concluída:** Function URL pública removida; os dois teardowns principais do Kong foram revalidados e aplicados; smoke pós-teardown aprovado. Não houve commit ou push.

### Lambda

- A reconciliação local já começou: `lambda.zip` foi sincronizado byte a byte ao pacote implantado; `handler.py` local foi copiado do mesmo pacote. O `CodeSha256` do ZIP implantado havia sido conferido antes da cópia. A variante local anterior do fonte foi preservada fora do checkout em `C:\Users\Maria\AppData\Local\Temp\opencode\handler-local-before-deployed-sync-20261013-183954.py`; o ZIP anterior em `C:\Users\Maria\AppData\Local\Temp\opencode\lambda-local-before-reconcile-20261013-181150.zip`.
- A função, handler e pacote Lambda não foram alterados. O hash do `lambda.zip` local confere com o pacote implantado.
- Os testes de configuração da Function URL passaram (4); os testes de validação de rotas e conta passaram (6); os testes Angular passaram (383) via `npm run test:ci`.
- O Plan `autoflow-lambda/infra/function-url-close-review.tfplan` foi validado contra refresh atual (0/0/3, sem drift e sem ação na função) e aplicado após autorização explícita. Apply: **0 add / 0 change / 3 destroy** (Function URL e duas permissões públicas).
- A Function URL agora retorna `ResourceNotFound`; a policy Lambda mantém a permissão `AllowAutoflowHttpApiLogin` de `apigateway.amazonaws.com`.
- Após a remoção da Function URL e os teardowns Kong, o smoke positivo autenticado passou: login HTTP 200, JWT emitido e aceito, consulta `GET /api/clientes/me/ordens-servico` HTTP 200 e frontend HTTP 200. Credenciais, token e corpos de resposta não foram registrados.

### Limpeza Kong e pipelines

- A limpeza local foi iniciada nos quatro repositórios. `autoflow` já não declara os Ingresses/Plugin/ExternalName Kong; manifests, chart acadêmico, workflow de regressão e documentação operacional foram removidos. NodePorts, ConfigMap Nginx, frontend, backend e API Gateway permanecem declarados.
- Pipelines de aplicação foram editadas para não instalar/verificar Kong. A pipeline Lambda foi adaptada para usar o pacote implantado ao planejar a remoção da URL.
- `autoflow-infra/infra/kong/` permanece como root temporário do teardown. `helm.tf` não declara mais a release, para produzir o Plan de exclusão; backend, providers, dados e values necessários ao root permanecem. Workflows, validador, gerador de certificado e README de provisionamento foram removidos. Não excluir o root antes do Apply aprovado.
- Plans regenerados contra os states atuais, sem drift e com escopo exato; Applies concluídos: aplicação **0/0/11** (9 Ingresses, 1 KongPlugin e 1 Service ExternalName) e Helm **0/0/1** (`helm_release.kong`). Nenhum recurso compartilhado foi incluído.

### Limpeza residual Kong — concluída

- A release Helm `autoflow-kong-academic` foi desinstalada após confirmar que não constava nos states Terraform. Foram removidos Service/Deployment/ConfigMap/ServiceAccount da release, ReplicaSet/Pod dependentes e Secret de histórico Helm. Não restaram Pods, Deployments ou Services associados.
- As 12 CRDs `configuration.konghq.com` foram revalidadas sem custom resources em todos os namespaces e removidas. A `IngressClass kong` já estava ausente.
- A busca em workloads não encontrou consumidores de `kong-homolog-tls`; o Secret foi removido. O namespace `kong` continha apenas recursos padrão e eventos históricos, sem referências externas, e foi excluído.
- Não foram encontrados NLB, Target Groups, ENIs ou regras SG com ownership/nome/portas do Kong antigo. ALB, Target Groups ativos e regras NodePort 30080/30081 foram preservados.
- O namespace `autoflow-auth-demo` permanece e contém somente `kube-root-ca.crt` e ServiceAccount `default` após o uninstall; não foi excluído.

### Estado Git observado na pausa

- `autoflow-infra`: alterações staged/unstaged de API Gateway, documentação, pipeline e teardown Kong; arquivos de provisionamento auxiliar Kong removidos; HCL/values do root de teardown mantidos.
- `autoflow`: pipeline, README, Terraform API Gateway, templates de Deployment e documentação alterados; manifests e código auxiliar Kong removidos; ferramentas de API Gateway adicionadas.
- `autoflow-lambda`: README, workflow, docs, HCL, testes e scripts alterados; `handler.py` sincronizado ao implantado; `test_http_api.py` adicionado. `lambda.zip` e plans são ignorados pelo Git.
- `autoflow-db`: README modificado e `docs/api-gateway.md` adicionado.
- Alterações preexistentes permanecem misturadas às mudanças desta sessão; não foram staged adicionalmente, revertidas ou commitadas durante o checkpoint.

## Evidências AWS homologadas em 13/10/2026

**Arquitetura final:** API Gateway HTTP API → integração nativa Lambda para login; VPC Link → ALB interno → EKS para frontend e backend; RDS PostgreSQL privado.

- API `4ct2k9m5l8`, 79 rotas, 48 integrações, stage `$default`.
- VPC Link `cjhmlk` `AVAILABLE`; ALB interno ativo.
- Target Groups backend e frontend: 2/2 `healthy`.
- EKS: 2/2 nós Ready; backend e frontend 1/1 Ready.
- RDS `available`; 47 migrations Flyway validadas, schema `public` atualizado, backend `db:UP`.
- Após a limpeza residual, login positivo, JWT, consulta autenticada, frontend, 12 assets e 3 deep links passaram; respostas HTTP do login, consulta e frontend: 200. Cada Target Group do ALB manteve 2/2 targets `healthy`; VPC Link, EKS e RDS permaneceram disponíveis.

## Reconciliação Lambda

- `lambda.zip` e `handler.py` locais foram sincronizados ao pacote implantado já homologado. Os artefatos locais anteriores foram preservados fora do checkout nos caminhos registrados no checkpoint de continuidade acima.
- Antes da sincronização, a única diferença de pacote era `handler.py`; a variante fonte aceitava também `cpf` e validava Base64 estritamente, enquanto a implantada aceita somente `cpf_cnpj` e decodifica Base64 permissivamente.
- Nenhum código foi publicado nem atualizado na AWS. A versão implantada continua sendo a aprovada pelo login positivo.

## Plans locais e status

| Repositório/arquivo local ignorado | Ações | Escopo |
|---|---:|---|
| `autoflow-lambda/infra/function-url-close-minimal.tfplan` | **OBSOLETO** | Gerado antes da remoção local da URL. Não aplicar. |
| `autoflow-lambda/infra/function-url-close-review.tfplan` | **APLICADO**: 0/0/3 | Consumido após aprovação; removeu Function URL e permissões públicas. Não reaplicar. |
| `autoflow/infra/kong-ingress-removal-revalidated.tfplan` | **APLICADO**: 0/0/11 | 9 Ingresses, 1 KongPlugin e 1 Service ExternalName; workloads e NodePorts 30080/30081 preservados. |
| `autoflow-infra/infra/kong/kong-removal-revalidated.tfplan` | **APLICADO**: 0/0/1 | Somente `helm_release.kong`; NLB e Target Groups do Service removidos pelo controlador. |

O NLB do Service `kong/kong-kong-proxy` foi identificado pela tag AWS `kubernetes.io/service-name` e está ausente após o Apply. Os Target Groups associados também foram removidos. Os Target Groups do ALB interno permanecem `healthy`; API Gateway, VPC Link, EKS e RDS estão disponíveis.

Os dois Plans foram regenerados contra os states atuais, sem drift, e aplicados após autorização específica. O Apply Helm também removeu a `IngressClass kong` como efeito da desinstalação; ela não foi removida por comando separado e não foi recriada.

## Resíduos no cluster após a limpeza final

- Não restaram releases Helm, CRDs `configuration.konghq.com`, `IngressClass`, Service, Pod ou workload ativo exclusivo do Kong.
- A namespace `autoflow-auth-demo` permanece com recursos padrão (`kube-root-ca.crt` e ServiceAccount `default`); não foi removida.
- Não foram encontrados recursos AWS residuais exclusivos do NLB antigo. ALB e portas 30080/30081 permanecem preservados.

## Verificações pós-limpeza

1. API Gateway: login/JWT/consulta autenticada HTTP 200; frontend, assets e deep links retornam HTTP 200.
2. Confirmar Target Groups backend/frontend do ALB com 2/2 targets `healthy` e VPC Link `AVAILABLE`.
3. Manter o namespace `autoflow-auth-demo`; qualquer limpeza adicional requer inventário e autorização específicos.

## Restrições de segurança e state

Plans e states podem conter dados sensíveis; não os versionar, publicar ou imprimir como JSON integral. Não executar `terraform state rm`, editar state manualmente, aplicar plano divergente ou destruir recursos compartilhados. Renovar credenciais Learner Lab e confirmar conta/região antes de cada operação aprovada.
