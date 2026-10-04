# AutoFlow infraestrutura

Repositório responsável pelo provisionamento da infraestrutura principal do **AutoFlow** na AWS utilizando **Terraform**.

## 🏗️ Infraestrutura

A infraestrutura provisionada inclui:

* **Amazon VPC**
* Subnets públicas e privadas em múltiplas Availability Zones
* **Amazon EKS** para execução da aplicação
* **EKS Managed Node Group** para os nós do cluster
* Security Groups
* Internet Gateway e rotas de rede
* IAM necessário para o funcionamento do EKS
* Integração com outros recursos da infraestrutura através de **Terraform Remote State**

O uso de Terraform permite manter a infraestrutura versionada, reproduzível e gerenciada como Infrastructure as Code.

## 📁 Estrutura

```text
autoflow-infra/
├── access-entry-eks.tf
├── backend.tf
├── eks-cluster.tf
├── eks-node.tf
├── internet-g.tf
├── route-t.tf
├── vars.tf
├── outputs.tf
├── providers.tf
├── data.tf
├── vpc.tf
└── README.md
```

## ☁️ AWS


O cluster EKS é utilizado como ambiente de execução dos componentes do AutoFlow, permitindo o gerenciamento dos workloads através do Kubernetes.

## 🚀 Comandos

Inicializar o Terraform:

```bash
terraform init
```

Validar a configuração:

```bash
terraform validate
```

Visualizar as alterações:

```bash
terraform plan
```

Aplicar a infraestrutura:

```bash
terraform apply
```

Remover a infraestrutura:

```bash
terraform destroy
```

Após a criação do EKS, o acesso ao cluster pode ser configurado com:

```bash
aws eks update-kubeconfig \
  --region us-east-1 \
  --name eks-autoflow-terraform
```

E verificado com:

```bash
kubectl get nodes
```

## 🔗 Integração

Os outputs deste repositório podem ser utilizados por outros repositórios Terraform através de **Remote State**, permitindo compartilhar informações como:

* VPC ID
* Subnet IDs
* Security Group IDs
* EKS cluster
* Região AWS

Essa separação mantém as responsabilidades da infraestrutura organizadas e facilita a evolução do projeto.

