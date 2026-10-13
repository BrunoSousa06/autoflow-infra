# Kong Gateway OSS + KIC (root de plataforma de homologação)

Este root Terraform pertence ao `autoflow-infra`. Ele instala Kong Gateway OSS, KIC e as CRDs do chart no cluster EKS existente. Deployments, Services, Ingresses e `KongPlugin` da aplicação permanecem em `autoflow`.

## Versões selecionadas e evidências de compatibilidade

| Componente | Versão fixa | Evidência |
|---|---|---|
| EKS/Kubernetes | `1.35` (existing cluster declaration; no upgrade here) | AWS lists EKS 1.35 in standard support. The KIC policy recommends KIC 3.5 for Kubernetes 1.35. |
| Kong Gateway OSS | `3.9.3`, image index `sha256:92035d16d7ff86b7bc12fb1d0090d29357d924238b1880f78735f3f2fea6b631` | The detailed KIC matrix lists Gateway 3.9.x with KIC 3.5.x. The official `kong` Docker Hub tag is available for amd64 and arm64. Kong OSS source release `3.9.4` was published on 2026-10-12, but that image tag was not available in Docker Hub during this check; pin the latest available exact image, not the mutable `3.9` tag. |
| Kong Ingress Controller | `3.5.13`, image index `sha256:979f12864a13031545d58623d17af7a071b417396fbb3928a169d897b056b68f` | Current supported KIC 3.5 LTS release; official KIC compatibility matrix lists Kubernetes 1.35 and Gateway 3.9.x for the 3.5 line. KIC v3.5.13 uses `kubernetes-configuration` v1.5.2. |
| Kong Helm chart | `3.4.1`, package digest `sha256:2c7dbf6bc59846d0c779e2509f45d041cc0dba5af85d6728294b9f37cd02e1d7` | Latest stable `kong` chart release in the official Kong chart repository. Its `appVersion: 3.9` is the chart's default only; Kong's KIC support policy says the chart is version-agnostic and supports selecting an image via values. |
| Helm CLI for static validation | `3.19.0` | Exact Helm v3 release used with the chart's v2 Chart.yaml; validation does not connect to EKS. |

As páginas de compatibilidade respondem a perguntas diferentes. A matriz detalhada enumera pares de versões secundárias testados e lista explicitamente Gateway 3.9.x como compatível com KIC 3.5.x. A política geral de suporte do KIC recomenda KIC 3.5 para Kubernetes 1.35 e apresenta uma faixa ampla Gateway `3.x`, alertando que essas versões podem ou não estar na janela de suporte atual do Kong Gateway. Esta configuração se baseia no par 3.9.x explícito, sem extrapolar a faixa ampla para 3.13–3.16.

A política de suporte do Gateway Enterprise não é tratada como garantia de suporte comercial ao OSS. Kong OSS `3.9.3` foi selecionado por ser a imagem oficial exata disponível que corresponde ao par testado na matriz KIC; isso não implica uso de imagem, licença ou suporte comercial Kong Enterprise. O código-fonte OSS no GitHub tem uma versão `3.9.4` mais recente, mas a imagem Docker correspondente não havia sido publicada no momento desta verificação. Atualize para uma imagem OSS mais recente somente após sua publicação e confirmação do par na matriz KIC.

O conjunto de CRDs do chart está identificado como `kubernetes-configuration` `v1.5.2`, correspondente à dependência no `go.mod` do KIC v3.5.13. O schema da CRD contém `KongPlugin.configFrom` e documenta seu uso para configuração sensível do plugin Lambda. O código do plugin AWS Lambda está incluído na imagem OSS do Gateway e a documentação do plugin lista DB-less como topologia compatível. `values.yaml` inclui explicitamente o nome do plugin embutido. Não há credenciais AWS no plugin; a role IRSA e a invocação efetiva ainda não estão implementadas nem validadas.

## Segurança e limites de implantação

- Kong está configurado em modo DB-less com imagem OSS. O KIC observa somente `default`; o Service do Admin API e os componentes Enterprise Manager/Portal/Portal API estão desabilitados.
- O Service proxy é `ClusterIP`. A configuração ainda não define encerramento TLS, annotations do controller de Load Balancer, hostname nem certificado; portanto, não é uma entrada HTTPS pública.
- O chart instala as CRDs na primeira instalação. Helm não atualiza CRDs existentes durante `helm upgrade`; atualize-as explicitamente para a versão de configuração KIC correspondente antes de atualizar a imagem KIC.
- Este root ainda não associa role IRSA. A role de privilégio mínimo deve ser configurada no ServiceAccount do dataplane antes de habilitar a rota de login da aplicação.
- Este root usa bucket/key fornecidos no `terraform init` por `-backend-config`, independentemente do state EKS. Configure os valores localmente por variáveis de ambiente ou em GitHub Actions Variables; não há arquivo HCL de exemplo versionado. Confirme ownership e reconciliação do state antes de inicializar. Não use este root até que a plataforma EKS esteja pronta e a API EKS acessível.

## Verificações estáticas locais

Com Helm `3.19.0` instalado, execute neste diretório:

```bash
bash ./validate.sh
terraform init -backend=false -input=false
terraform fmt -check -recursive
terraform validate
```

Essas verificações renderizam localmente o chart e as CRDs fixadas. Não aplicam recursos, acessam EKS, inspecionam/inicializam o backend remoto nem chamam APIs AWS. Carregamento do plugin em runtime, IRSA, comportamento do chart no cluster real e admissão das CRDs pelo EKS continuam sendo gates de ambiente.
