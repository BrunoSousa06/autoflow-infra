# Progresso da implementação — Disaster Recovery

**Documento de requisitos:** [`../../../../docs/specs/aws-academy-disaster-recovery/implementation-plan.md`](../../../../docs/specs/aws-academy-disaster-recovery/implementation-plan.md) no workspace compartilhado. O plano foi lido integralmente antes das alterações.

> Atualização: os protótipos de bootstrap de bucket e guard de recuperação foram removidos a pedido do operador por estarem fora do escopo. Neste checkout, os arquivos do coletor de inventário citados no registro histórico não estão presentes; o runbook de diagnóstico EKS permanece disponível. Este documento não representa uma implementação de Disaster Recovery ativa.

| ID do plano | Estado | Repositório/arquivos | Verificação e pendências |
| --- | --- | --- | --- |
| T01 | REGISTRO HISTÓRICO | Workspace e evidências do inventário anteriormente coletadas | Inventário anterior registrou as cinco keys e dependências; os arquivos-fonte do coletor não estão neste checkout. |
| T02 | PARCIALMENTE VALIDADO; BLOQUEADO | Perfil AWS `fiap-lab`, GitHub CLI | STS/conta confirmada; APIs read-only dos serviços e Service Quotas foram acessíveis; sem AccessDenied nas chamadas do inventário. Operações Create/Put/RunInstances/PassRole não foram tentadas. SCP no worker role, folga/custo Academy, GitHub Required reviewers e conectividade HTTPS/SSM permanecem sem confirmação. |
| T03 | REMOVIDO DO ESCOPO | Protótipo `recovery_state_guard.py` e teste removidos | Não implementar guard nem fluxo de recuperação. |
| T04 | REMOVIDO DO ESCOPO | Protótipo `bootstrap_state_bucket.py` e teste removidos | Não criar/configurar bucket nesta tarefa. |
| Diagnóstico preservado | MANTIDO | `docs/eks-node-recovery.md` e registro histórico deste diretório | Não há automação de recuperação ativa. |
| T05–T10 | PENDING | Conforme plano principal | Não iniciados nesta execução; nenhuma fase posterior foi iniciada. |

**Testes executados:**

```bash
terraform fmt -check -recursive infra
terraform -chdir=infra init -backend=false -input=false
terraform -chdir=infra validate
git diff --check
```

**Resultados anteriores à continuação:** scripts T03/T04 tiveram 4 testes de bucket, 9 testes de state guard; suíte 27 testes e validações Terraform passaram.

**Resultados históricos anteriores:** testes de inventário (9 cenários) passaram quando o coletor estava presente; antes da remoção dos protótipos, a suíte continha 36 testes. Esses resultados não validam a implementação atual do runner nem o conteúdo deste checkout.

**Atualização da tarefa do runner:** em execução anterior, Terraform `fmt -check`, `init -backend=false` e `validate` passaram, assim como 23 testes encontrados naquele momento. No checkout revisado depois, `scripts/test_inventory_recovery.py` não pode ser importado porque `inventory_recovery.py` não existe; esse teste órfão foi preservado fora do commit. Nenhum `plan/apply/destroy` foi executado. Consulte `docs/github-runner.md` para limitações e ativação.

**Estado operacional:** somente chamadas AWS read-only pelo perfil `fiap-lab`; sem Terraform Apply/Destroy, sem criação/exclusão de bucket, sem alteração de SG/endpoint EKS, IAM, workflows ou secrets; sem commit/push/merge. O GitHub CLI não tinha autenticação.

**Estado deste registro:** histórico de análise de Disaster Recovery, fora do escopo ativo. O runbook de diagnóstico EKS permanece; não há próxima tarefa de recuperação autorizada.
