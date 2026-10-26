# Diagnóstico e recuperação dos nós EKS

## Estado da investigação

O sintoma informado é: `nodeg-autoflow` ACTIVE, duas EC2 `running`, nenhum Node registrado e CoreDNS Pending após reinicialização do Learner Lab. O reboot individual já recuperou o registro uma vez, mas isso não identifica sozinho a causa.

### Evidências locais

- `infra/eks-node.tf` declara um managed node group padrão (`aws_eks_node_group`) com duas instâncias desejadas e não declara `launch_template`, `ami_type`, AMI própria ou `user_data`.
- `infra/eks-cluster.tf` declara Kubernetes `1.35`. AWS documenta que managed node groups novos em clusters Kubernetes `1.30+` adotam AL2023 por padrão. O AMI efetivamente executado pelo node group atual não foi consultado.
- IAM de cluster e node é fornecido externamente por `AWS_EKS_CLUSTER_ROLE_ARN`/`AWS_EKS_NODE_ROLE_ARN`; este repositório não cria roles/policies. O workflow agora executa preflight read-only de existência, trust policy e AWS managed policies requeridas; isso só comprova o resultado na execução autorizada e não corrige configuração IAM.
- A VPC declara subnets públicas com IP público automático, IGW e egress no SG. Isso é configuração versionada; não comprova rotas, SG efetivo, SCP, nem conectividade atual do runtime.
- Não existe configuração de bootstrap `nodeadm` explícita no Terraform; o EKS gerencia o launch template e user data do managed node group.
- Nesta sessão, `aws sts get-caller-identity` não encontrou credenciais válidas e não foi possível consultar EC2, EKS, CloudTrail ou logs dos nós. `kubectl` está instalado, mas não foi usado sem identidade AWS/cluster autorizada.

### Causa e limites da conclusão

O relato de log fornecido pelo operador aponta uma negação explícita por SCP a `ec2:DescribeInstances`. Isso é evidência externa desta conversa, ainda não corroborada com logs acessíveis nesta sessão. O código upstream do `nodeadm` mostra que, sem configuração em cache, a inicialização enriquece a configuração chamando `api.GetInstanceDetails` com um cliente EC2 `DescribeInstances`. O log do `nodeadm` que reporta essa chamada é, portanto, tecnicamente compatível com a implementação.

O código upstream consultado é a branch `main`, não necessariamente a versão exata do AMI instalado. O AMI, versão do `nodeadm`, conteúdo de user data e CloudTrail da ocorrência precisam ser obtidos para fechar essa atribuição. A sequência “falha negada → reboot individual → registro” comprova correlação, não prova que o reboot corrigiu a política. A explicação mais provável é uma chamada de bootstrap não autorizada por SCP; permanecem hipóteses de retry/propagação temporal de identidade e de configuração/AMI diferente do esperado.

Uma negação explícita por SCP prevalece sobre permissões Allow de IAM anexadas à role. Portanto, anexar `AmazonEKSWorkerNodePolicy` ou uma policy customizada não resolve uma negação SCP. Também não recomendamos contornar a verificação de identidade EC2 ignorando `DescribeInstances`: a inicialização/identificação e funcionamento do kubelet/CNI dependem de dados da instância e chamadas AWS. Remover chamadas sem validar quais componentes as emitem pode apenas mudar o erro de fase.

### Impacto potencial de uma alteração Terraform

Não alterar `aws_eks_node_group` para adicionar launch template, AMI ou bootstrap como tentativa de correção. A AWS não permite migrar diretamente um managed node group existente, criado sem launch template customizado, para um launch template customizado; a alternativa normalmente requer um novo node group e migração dos workloads. Mudança de versão do launch template pode reciclar todas as EC2 do grupo. Alterações de AMI/release também substituem instâncias. Um plan pode mostrar replacement ou update que dispara rolling update; revisar todos os endereços e ações com cuidado. Nenhum plan/apply foi executado nesta investigação.

## Auditoria do bootstrap e chamadas AWS

1. O managed node group sem launch template customizado recebe recursos/user data controlados pelo EKS. Para AL2023, a inicialização usa `nodeadm`; a configuração mínima do NodeConfig contém nome do cluster, endpoint, CA e CIDR de Service.
2. O `nodeadm` lê user data via IMDS (`imds://user-data`), podendo ler metadados/identity document local sem fazer chamadas autenticadas ao EC2 API.
3. No caminho de configuração não coberto por cache, o código upstream chama `DescribeInstances` para coletar detalhes da instância usados pelo bootstrap. A VPC CNI e o kubelet podem também fazer chamadas EC2 no funcionamento normal; a role de worker normalmente requer permissões de descrição EC2.
4. AL2023 evita descobrir os metadados do cluster via `eks:DescribeCluster` quando a configuração cluster está explícita; isso não elimina por si só `ec2:DescribeInstances` usado para detalhes da instância.
5. Provisionar launch template customizado/UserData/AMI não é correção comprovada para uma SCP que nega `DescribeInstances`. Também introduz responsabilidade de bootstrap e pode obrigar migração de node group.

Fontes consultadas:

- [AWS — Customize managed nodes with launch templates](https://docs.aws.amazon.com/eks/latest/userguide/launch-templates.html): comportamento de UserData/AL2023 e metadados obrigatórios para AMI customizada.
- [AWS — Create nodes with optimized Amazon Linux AMIs](https://docs.aws.amazon.com/eks/latest/userguide/eks-optimized-ami.html): AL2023 padrão para managed node groups novos em Kubernetes 1.30+.
- [AWS — Amazon EKS node IAM role](https://docs.aws.amazon.com/eks/latest/userguide/create-node-role.html): permissões usuais para worker nodes e EC2.
- [AWS — Troubleshoot EKS nodes](https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html): node join, rede, node role e log collector.
- [Amazon EKS AMI — nodeadm init](https://github.com/awslabs/amazon-eks-ami/blob/main/nodeadm/cmd/nodeadm/init/init.go) e [API de detalhes da instância](https://github.com/awslabs/amazon-eks-ami/tree/main/nodeadm/internal/api): implementação upstream; conferir a versão correspondente ao AMI antes de tratar como prova da versão runtime.

## Correção persistente recomendada

Não foi feita alteração Terraform: o código não administra a SCP nem a policy/role real do node group, e não há evidência live para provar qual resource/policy gera o Deny. A correção duradoura depende do administrador do AWS Academy confirmar no SCP/effective permissions se `ec2:DescribeInstances` pode ser permitido para o contexto/role de worker, ou indicar o fluxo de exceção suportado pelo laboratório. Se SCP não puder ser alterada, a equipe deve validar com AWS Academy uma estratégia suportada que não exija essa API; não há workaround Terraform local comprovadamente seguro. Não adicionar IAM Allow como paliativo nem adotar AMI/user data customizados sem teste em node group isolado e revisão do plano.

## Diagnóstico EC2 versus Kubernetes

Com AWS CLI autenticada na conta correta e kubeconfig para `eks-autoflow`, executar apenas leituras:

```bash
python scripts/diagnose_eks_nodes.py --cluster eks-autoflow --nodegroup nodeg-autoflow --region us-east-1
```

O script compara instâncias `running` do Auto Scaling Group do node group com `spec.providerID` e condição `Ready` em Nodes Kubernetes. Exit code `0` indica correspondência; `2` indica discrepância; `1` indica que não foi possível coletar estado. Permissões necessárias: `eks:DescribeNodegroup`, `autoscaling:DescribeAutoScalingGroups`, `ec2:DescribeInstances` e acesso Kubernetes de leitura para `get nodes`. Os IDs reportados não incluem credenciais. O script é somente leitura.

Coleta adicional somente leitura para triagem autorizada:

```bash
aws sts get-caller-identity
aws eks describe-cluster --name eks-autoflow --region us-east-1 --query 'cluster.{version:version,status:status,endpoint:resourcesVpcConfig.endpointPublicAccess,private:resourcesVpcConfig.endpointPrivateAccess,subnets:resourcesVpcConfig.subnetIds}'
aws eks describe-nodegroup --cluster-name eks-autoflow --nodegroup-name nodeg-autoflow --region us-east-1 --query 'nodegroup.{status:status,health:health,amiType:amiType,releaseVersion:releaseVersion,version:version,nodeRole:nodeRole,launchTemplate:launchTemplate,instances:resources.autoScalingGroups}'
kubectl get nodes -o wide
kubectl -n kube-system get pods -o wide
```

Para cada instância (sem exibir credenciais nem dados de user data sensíveis), consultar EC2 console → **Get system log** e CloudTrail Event history com filtro por `eventName=DescribeInstances`, janela do boot, role assumida e `errorCode/errorMessage`. Confirmar logs `nodeadm` por Session Manager se disponível: `sudo journalctl -u nodeadm-config.service -b --no-pager`, `sudo journalctl -u nodeadm-run.service -b --no-pager`, `sudo journalctl -u kubelet -b --no-pager` e `/var/log/cloud-init-output.log`. SSM exige agente e permissões previamente disponíveis; não alterar IAM/network para esta coleta sem autorização.

## Recuperação manual individual

Executar somente com autorização operacional, fora de Terraform/CI. Não reiniciar os dois nós simultaneamente.

1. Registrar os instance IDs e o estado inicial com o script acima. Verificar se CoreDNS está Pending por falta de nós, usando `kubectl -n kube-system describe pod -l k8s-app=kube-dns`.
2. No console EC2, selecionar uma única instância `running` do node group e usar **Instance state → Reboot instance**. Não usar terminate/stop/start e não alterar desired capacity. Esperar a instância voltar a `running` e aguardar o boot.
3. Acompanhar o registro: `kubectl get nodes -w`. Confirmar que o Node cujo `providerID` termina no ID reiniciado aparece e fica `Ready` (`kubectl describe node <nome>`); validar também os pods `aws-node` e `kube-proxy` naquele nó.
4. Reexecutar `python scripts/diagnose_eks_nodes.py ...`; só prosseguir ao segundo nó depois da primeira EC2 estar correspondente a um Node `Ready`.
5. Repetir os passos para a segunda instância. Ao final, confirmar duas instâncias correspondentes e `Ready`, e CoreDNS `Running`/`Ready`.
6. Se o primeiro reboot não registrar o nó ou surgir novo `AccessDenied`, interromper a recuperação e preservar timestamps/logs/CloudTrail para o administrador do SCP. Não repetir reboot indefinidamente.

O reboot é recuperação emergencial, não correção da política e não é executado por Terraform ou CI/CD.
