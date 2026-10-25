# Runbook: transferência controlada do state New Relic

Este procedimento cobre somente a transferência de ownership Terraform entre `infra/` e `infra/newrelic/`. Não foi executado contra AWS ou New Relic. Nenhum workflow realiza esses passos automaticamente.

## Regras de segurança

1. Obter autorização explícita do owner de infraestrutura e janela de mudança. Desabilitar temporariamente ambos os workflows para evitar deploy concorrente; congelar mudanças manuais nos objetos New Relic.
2. Confirmar conta/região AWS, bucket e keys dos dois Environments. Não confundir a User API key do provider com a License Key de ingestão.
3. Com backend correto inicializado em cada root, registrar `terraform state list` em diretório restrito. Inspecionar endereços reais e módulos/índices retornados; nunca deduzir `[0]` ou chaves de `for_each` pelo código atual. A saída de `terraform state show` pode conter valores sensíveis: não anexar a tickets, logs ou artifacts.
4. Confirmar cada objeto remoto por refresh/read-only APIs/Helm, comparando account, ambiente, cluster, namespace e identidade. AccessDenied, timeout, API indisponível ou resposta ambígua significa parar, não significa ausência.
5. Criar backup de cada state com `terraform state pull`, em local criptografado, acesso mínimo e retenção aprovada. Registrar hash, versão e horário sem publicar o conteúdo; confirmar leitura do backup antes de prosseguir.
6. Garantir que somente um root terá ownership após cada etapa. Plan destrutivo do root antigo permanece bloqueado pelo guard `check-legacy-plan`; não usar `allow_destructive` para contorná-lo.

## Inventário e decisão

Com backend/key corretos inicializados, executar `terraform state list` separadamente em `infra/` e `infra/newrelic/`, salvando a saída restrita. O script `scripts/newrelic_state_guard.py` testa states JSON sintéticos e bloqueia address legado, duplicação, state novo sem recurso remoto correspondente, recurso remoto sem ownership no state novo e inventário remoto inconclusivo. State novo não vazio é permitido no deploy normal quando o inventário confirma objetos remotos correspondentes. O CI usa state pull em arquivos temporários protegidos; runners descartáveis removem esses conteúdos ao final do job.

Exemplo de inspeção depois de confirmar bucket/key autorizados (os comandos leem state; a saída deve permanecer em diretório restrito):

```bash
terraform -chdir=infra init -input=false -backend-config="bucket=$AWS_TERRAFORM_STATE_BUCKET" -backend-config="key=$AWS_TF_STATE_KEY_INFRA" -backend-config="region=$AWS_REGION" -backend-config="encrypt=true" -backend-config="use_lockfile=true"
terraform -chdir=infra state list
umask 077
terraform -chdir=infra state pull > "$SECURE_BACKUP_DIR/infra-before.json"
terraform -chdir=infra/newrelic init -input=false -backend-config="bucket=$AWS_TERRAFORM_STATE_BUCKET" -backend-config="key=$AWS_TF_STATE_KEY_NEWRELIC" -backend-config="region=$AWS_REGION" -backend-config="encrypt=true" -backend-config="use_lockfile=true"
terraform -chdir=infra/newrelic state list
terraform -chdir=infra/newrelic state pull > "$SECURE_BACKUP_DIR/newrelic-before.json"
```

`$SECURE_BACKUP_DIR` deve existir em armazenamento criptografado/restrito. Não imprimir, anexar ou versionar os arquivos. Calcular hashes sem exibir conteúdo e validar que os backups podem ser lidos antes de qualquer alteração.

- Sem endereço New Relic em nenhum state e objetos remotos comprovadamente ausentes: é cenário A; não há migração.
- Endereço registrado no root antigo: cenário B; mapear o endereço retornado para o endereço declarado atual e documentar o ID/import ID do recurso, usando documentação do provider para a versão travada.
- Se houver address no state antigo mas o objeto remoto estiver comprovadamente ausente, não importar; somente com autorização explícita remover a referência órfã e confirmar que o Plan não propõe destroy/criação indevida.
- Objeto remoto existente sem state no novo root, ou recursos existentes fora do conjunto de nomes esperados: parar e ampliar inventário. A pipeline bloqueia criação automática.
- Endereço em ambos os states: conflito; nenhum Plan/Apply normal pode prosseguir.

## Transferência autorizada

1. Capturar e revisar o inventário. Para cada recurso, conferir `type`, `name`, módulo e `index_key` efetivamente armazenados; relacionar ao endereço declarativo do root novo. A tabela de migração deve ser aprovada antes da alteração.
2. Enquanto ainda houver recursos NR no state antigo, não executar Plan no root antigo: o guard pré-Plan bloqueia o workflow principal para evitar Plan destrutivo. Depois de transferir/remover as referências antigas, gerar Plan somente leitura do root antigo e registrar o resultado sanitizado.
3. Transferir um recurso por vez. A operação autorizada deve remover o endereço específico do state antigo sem destruir o objeto (`terraform state rm '<endereço-exato>'`) e importar no novo endereço (`terraform import '<endereço-novo-exato>' '<ID de import documentado pelo provider>'`). Nunca usar wildcard, assumir índice nem editar JSON de state.
4. Após cada transferência, confirmar: endereço ausente no state antigo; endereço presente uma única vez no state novo; objeto remoto ainda presente. Fazer backup dos dois states após cada unidade concluída.
5. Quando todos forem transferidos, executar refresh/Plan independente dos dois roots. O root antigo não pode propor destroy de recursos New Relic. O root novo não pode propor create, replace ou destroy para recursos migrados; aceitar somente `no-op`/mudanças in-place revisadas e explicadas.
6. Só reabilitar os workflows após aprovação dos dois Plans, confirmação do owner e revisão de conta/região/cluster. Aplicar primeiro o root novo apenas se o Plan não recriar/substituir recursos migrados; Plan/Apply não substitui os comandos manuais de transferência.

O `terraform state mv` entre backends distintos não é tratado como mecanismo automatizado: usar apenas se o operador validar compatibilidade da versão/backend e possuir procedimento específico testado. O procedimento padrão acima usa remoção sem destroy seguida de import com ownership exclusivo.

## Recuperação e rollback parcial

- Falha antes de remover endereço antigo: interromper; nenhum recurso remoto deve ser alterado.
- Falha depois do `state rm`, antes do import: manter deploys congelados; confirmar remoto; restaurar state antigo do backup ou completar import aprovado. Não executar Apply em nenhum root.
- Falha depois do import: se os dois states contiverem o mesmo objeto, congelar ambos; remover apenas a referência duplicada, mediante aprovação, após confirmar remoto e backups. Não destruir objeto.
- Divergência de Plan: interromper e reconciliar estado/endereço/import ID. Não aceitar create/delete/replace como correção automática.
- State corrompido/perdido: recuperar versão S3/backup validado com procedimento de recuperação aprovado e lock do backend; nunca sobrescrever cegamente nem expor state em logs.

Qualquer rollback deve deixar o recurso sob ownership de exatamente um root. Reverter código para restaurar declaração no root antigo exige uma transferência controlada de volta e Plans de ambos os roots antes de reativar CI/CD.
