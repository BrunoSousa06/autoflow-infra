# Diagnóstico e manutenção de nós EKS

O diagnóstico dos nodes usa `scripts/diagnose_eks_nodes.py` para comparar instâncias `running` do Auto Scaling Group com
Nodes Kubernetes registrados e em estado `Ready`. O comando é somente leitura:

```bash
python scripts/diagnose_eks_nodes.py --cluster eks-autoflow --nodegroup nodeg-autoflow --region us-east-1
```

Para produção, use `eks-autoflow-production` e `nodeg-autoflow-production`. O código de saída `0` indica correspondência,
`2` indica discrepância e `1` indica falha de coleta. São necessários `eks:DescribeNodegroup`,
`autoscaling:DescribeAutoScalingGroups`, `ec2:DescribeInstances` e acesso Kubernetes de leitura a `nodes`.

## Verificação

1. Confirme conta e região com `aws sts get-caller-identity` e a configuração local do `kubectl`.
2. Verifique o estado e a saúde do managed node group e compare o número de EC2 `running` com a capacidade desejada.
3. Confira os Nodes em estado `Ready` e os pods de sistema, incluindo `aws-node`, `kube-proxy` e CoreDNS.
4. Se houver divergência, consulte logs do EKS/EC2 e eventos do Kubernetes para identificar a causa antes de alterar a
   infraestrutura.

## Recuperação

Corrija o item identificado no root ou serviço que o administra e revise o Terraform Plan antes do Apply. Alterações de
AMI, launch template, user data, IAM, rede ou capacidade do node group podem substituir ou reiniciar instâncias; faça-as
por uma mudança declarativa aprovada. Não edite State manualmente nem altere simultaneamente todos os nodes durante uma
intervenção.
