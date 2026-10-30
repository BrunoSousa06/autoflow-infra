# Runbook do orquestrador de pipelines AutoFlow

## Execução operacional

1. Confirme que a sessão de `gh` pode consultar os quatro repositórios e que o shell é Windows PowerShell 5.1 ou posterior.
2. Execute primeiro um dry-run para conferir o escopo das consultas:

   ```powershell
   .\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action report -DryRun
   ```

3. Consulte o ambiente escolhido:

   ```powershell
   .\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action status
   .\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action validate
   .\scripts\orchestration\Invoke-AutoFlowPipeline.ps1 -Environment homolog -Action report
   ```

4. Se necessário, exporte o relatório para um diretório local apropriado. Não grave arquivos com valores de Secrets ou tokens.
5. Encaminhe os IDs/URLs de execuções e códigos de inconsistência para análise manual nos repositórios/GitHub Environments correspondentes. Mantenha as aprovações e gates nativos.

## Diagnóstico por resultado

| Resultado | Ação manual sugerida |
|---|---|
| `ACCESS_DENIED` / HTTP 403 | Solicitar a permissão de leitura mínima para aquele repositório/endpoint. Não alterar Environments nem usar token administrativo próprio da ferramenta. |
| `RATE_LIMIT` / HTTP 429 | Aguardar a janela de rate limit e repetir a consulta; não aumentar permissões como primeira medida. |
| `NOT_FOUND` em Environment, após o repositório confirmado | Confirmar manualmente o nome exato do GitHub Environment e a branch esperada. |
| `NOT_FOUND_OR_NOT_VISIBLE` em repositório | Confirmar acesso ao nome configurado; um 404 de repositório privado pode ocultar falta de acesso. |
| `ENVIRONMENT_UNKNOWN` após 404 | Consultar manualmente o inventário de Environments com identidade autorizada. O endpoint direto 404 não confirma ausência. |
| `MISSING_ENVIRONMENT` | Inventário de Environments acessível respondeu validamente sem o nome solicitado; revisar nome/escopo no GitHub. |
| `TIMEOUT` | Repetir a consulta em outro momento e verificar a conectividade com GitHub. A chamada interrompida não é repetida automaticamente. |
| `API_UNAVAILABLE` / HTTP 5xx | Consultar disponibilidade do GitHub e tentar novamente mais tarde. |
| `INVALID_RESPONSE` | Guardar apenas o identificador do recurso e horário da consulta; não copiar headers, tokens ou respostas completas para logs. |
| `UNKNOWN` | Não tratar como ausência ou aprovação. Repetir a consulta ou verificar manualmente com acesso autorizado. |
| `REQUIRED_REVIEWERS_MISSING` | Revisar manualmente proteção e reviewers no GitHub Environment. A ferramenta não configura nem aprova a proteção. |
| `BRANCH_POLICY_*` | Confirmar se a política configurada admite somente a branch correspondente (`develop`/`main`) e se a branch exigida existe/está protegida. |
| `APPLY_APPROVAL_DISABLED` (`OPERATIONAL_BLOCKED`) | `TERRAFORM_APPLY_APPROVAL_CONFIGURED=false` bloqueia o Apply intencionalmente. Mantenha o valor e os gates nativos; o Orchestrator não autoriza nem contorna o bloqueio. |
| `APPROVAL_MARKER_INVALID` | Corrigir o valor para `true` ou `false`; não habilitar `true` sem a auditoria dos reviewers e branch policy. |
| `TERRAFORM_STATE_CONTRACT_INVALID` | Comparar as seis State Keys e as referências produtor/consumidor das Variables nos dois ambientes. Use o resultado do validador existente; não edite States remotos. |
| `failure`, `cancelled` ou `skipped` | Abrir manualmente a URL do run/job e inspecionar o GitHub Actions. O orquestrador não baixa logs nem reexecuta workflows. |
| `waiting` | Verificar o run e a página do Environment no GitHub. A resposta pode não revelar o motivo nem o aprovador. |
| `ApprovalPending` confirmado | A API `pending_deployments` retornou Environment, reviewer count e `current_user_can_approve`; revisar manualmente no GitHub. O orquestrador não aprova. |
| `pending_deployments` com erro de consulta | Manter a aprovação como `UNKNOWN`; não concluir que não há gate pendente. Verificar acesso de leitura à API Actions e consultar o run manualmente. |

## Segurança e resposta a incidentes

- Não execute ações de escrita por meio do orquestrador; as únicas ações aceitas são `status`, `validate` e `report`.
- O programa não chama AWS e não lê Secrets. A consulta a GitHub Secrets retorna somente nomes.
- Evite anexar respostas brutas de API, arquivos temporários, tokens ou valores de Variables em tickets/logs. O relatório exportado é local, contém somente nomes de Variables/Secrets e achados redigidos.
- Se uma consulta retornar conteúdo inválido ou informação incompleta, preserve `UNKNOWN` e investigue manualmente; não converta o resultado em “configurado” ou “ausente”.
- Um run concluído com sucesso não é confirmação de AWS provisionada. Confirme recursos por um processo operacional separado e autorizado.

## Testes e manutenção

Execute os testes Pester com mocks antes de alterar o orquestrador:

```powershell
Invoke-Pester -Path .\scripts\orchestration\tests\AutoFlow.Orchestration.Tests.ps1 -Verbose
```

O fluxo de consulta e a allowlist vivem em `scripts/orchestration/`. O contrato dos seis States é mantido exclusivamente em `scripts/terraform_state_contract.py`; mudanças no seu comportamento exigem trabalho separado e testes próprios.
