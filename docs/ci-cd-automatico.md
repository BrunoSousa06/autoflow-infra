# Início automático do CD

Os workflows de CD recebem `push` em `develop` ou `main`, mas o gate consulta e aguarda a execução de `.github/workflows/ci.yml` para a mesma branch e o mesmo SHA. Somente a conclusão `success` da CI exata libera o Plan. A Variable externa `AUTO_CD_ENABLED`, no Environment de destino, controla o início automático: somente o valor literal `true` habilita o gate; variável ausente ou qualquer outro valor o mantém desabilitado. Nenhuma variável, Secret, Environment ou regra de proteção é criada por este código.

No repositório `autoflow-infra`, essa configuração habilita separadamente as três pipelines existentes (VPC/EKS, HTTP API Gateway e New Relic) após a CI comum validar os respectivos roots. Cada CD continua independente e executa seu próprio Plan; os seis Terraform roots permanecem separados.

O gate usa o token padrão com leitura de Actions para consultar a API do GitHub por até 30 minutos. Ele confirma o nome e o evento `push` da CI, o repositório, a branch, o SHA e a conclusão. Ausência de execução, falha, cancelamento, conclusão `skipped`, divergência ou timeout bloqueia o Plan. O checkout usa o SHA validado e compara `git rev-parse HEAD` antes de acessar AWS. PRs e branches `feature/**` não são gatilhos. `main` também precisa estar protegida.

Foi escolhido `push` com espera e validação da CI por API, em vez de `workflow_run`: a branch padrão do repositório varia entre os quatro projetos, enquanto os PRs desta entrega têm destino `develop`; esse mecanismo mantém a definição do CD na branch alvo sem `actions:write` ou re-disparo por token privilegiado. Para cada repositório, `AUTO_CD_ENABLED` pode ser configurada separadamente nos Environments `homolog` e `production`, permitindo ativação independente por ambiente. Enquanto a variável estiver ausente ou diferente de `true`, o gate não libera Plan nem operações AWS. Os Plans automáticos continuam vinculados ao Environment selecionado e às suas aprovações Required Reviewers; essa aprovação de Plan não autoriza Apply. Os Plans de VPC/EKS e New Relic podem fazer a autorização temporária de endpoint já prevista no fluxo.

O caminho automático não executa Apply. Apply continua disponível somente por `workflow_dispatch` com `apply=true`, aprovação efetiva de Required Reviewers no Environment selecionado e `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`. A aprovação de Environment para um Plan automático ou manual não autoriza o Apply, que exige execução separada e nova autorização. O fluxo manual Plan-only permanece disponível com `apply=false`.

## Configuração externa

- Para habilitar homologação, criar fora deste PR a Variable `AUTO_CD_ENABLED=true` no Environment `homolog`; para habilitar produção, criá-la separadamente no Environment `production`. Variável ausente ou diferente de `true` mantém o respectivo ambiente desabilitado.
- Fazer a configuração separadamente em cada repositório. Em `autoflow-infra`, uma Variable por Environment habilita as três pipelines independentes desse repositório.
- A configuração exige apenas uma Variable não sensível; não exige Secret novo nem ID de conta. Os CD jobs continuam reutilizando as configurações AWS, States, criptografia e gates já existentes em cada Environment.

O gate automático apenas inicia os jobs de Plan após a CI aprovada. As proteções próprias do Environment continuam aplicáveis. Nenhuma implantação ou operação AWS é inferida como realizada por esta configuração local.
