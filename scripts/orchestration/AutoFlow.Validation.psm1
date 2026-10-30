Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'AutoFlow.Config.psm1')
Import-Module (Join-Path $PSScriptRoot 'AutoFlow.GitHub.psm1')

function Add-AutoFlowFinding {
    param(
        [System.Collections.Generic.List[object]]$Findings,
        [string]$Code,
        [string]$State,
        [string]$Repository,
        [string]$Environment,
        [string]$Message
    )
    [void]$Findings.Add([pscustomobject]@{
        Code = $Code
        State = $State
        Repository = $Repository
        Environment = $Environment
        Message = $Message
    })
}

function Add-AutoFlowValidationQueryError {
    param([System.Collections.Generic.List[object]]$Errors, [string]$Repository, [string]$Resource, $Response)
    [void]$Errors.Add([pscustomobject]@{
        Repository = $Repository
        Resource = $Resource
        Kind = [string]$Response.ErrorKind
        StatusCode = [int]$Response.StatusCode
        Message = [string]$Response.Message
    })
}

function Test-AutoFlowCorsValue {
    param([string]$Value)
    try {
        Add-Type -AssemblyName System.Web.Extensions -ErrorAction SilentlyContinue
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $parsed = $serializer.DeserializeObject($Value)
        if ($parsed -isnot [System.Array]) { return $false }
        foreach ($origin in $parsed) {
            if ($origin -isnot [string] -or [string]::IsNullOrWhiteSpace($origin)) { return $false }
        }
        return $true
    } catch {
        return $false
    }
}

function Test-AutoFlowEnvironmentProtection {
    param(
        $EnvironmentData,
        [string]$ExpectedBranch,
        [string]$OtherEnvironmentBranch,
        [string]$Repository,
        [string]$FullName,
        [string]$Environment,
        [scriptblock]$ApiInvoker,
        [System.Collections.Generic.List[object]]$Findings,
        [System.Collections.Generic.List[object]]$QueryErrors
    )

    $rules = @()
    $reviewerListKnown = (Test-AutoFlowObjectProperty $EnvironmentData 'protection_rules') -and $EnvironmentData.protection_rules -is [System.Array]
    if (-not $reviewerListKnown) {
        Add-AutoFlowFinding $Findings 'REQUIRED_REVIEWERS_UNKNOWN' 'UNKNOWN' $Repository $Environment 'A API nao retornou uma lista valida de protection_rules.'
    } else {
        $rules = @($EnvironmentData.protection_rules)
    }
    $reviewerCount = 0
    foreach ($rule in $rules) {
        if (-not (Test-AutoFlowObjectProperty $rule 'type') -or $rule.type -isnot [string]) {
            Add-AutoFlowFinding $Findings 'INVALID_PROTECTION_RULE' 'UNKNOWN' $Repository $Environment 'Uma protection rule retornada nao possui type valido.'
            $reviewerListKnown = $false
            continue
        }
        if ($rule.type -eq 'required_reviewers') {
            if (-not (Test-AutoFlowObjectProperty $rule 'reviewers') -or $rule.reviewers -isnot [System.Array]) {
                Add-AutoFlowFinding $Findings 'INVALID_REVIEWER_POLICY' 'UNKNOWN' $Repository $Environment 'A API nao retornou a lista de Required reviewers.'
                $reviewerListKnown = $false
                continue
            }
            foreach ($reviewer in @($rule.reviewers)) {
                if (-not (Test-AutoFlowObjectProperty $reviewer 'type') -or $reviewer.type -isnot [string] -or [string]::IsNullOrWhiteSpace($reviewer.type)) {
                    Add-AutoFlowFinding $Findings 'INVALID_REVIEWER_POLICY' 'UNKNOWN' $Repository $Environment 'Um Required reviewer retornado nao possui type valido.'
                    $reviewerListKnown = $false
                } else {
                    $reviewerCount++
                }
            }
        }
    }
    if ($reviewerCount -eq 0 -and $reviewerListKnown) {
        Add-AutoFlowFinding $Findings 'REQUIRED_REVIEWERS_MISSING' 'INCONSISTENT' $Repository $Environment 'Nenhum Required reviewer foi confirmado pela API.'
    }

    if (-not (Test-AutoFlowObjectProperty $EnvironmentData 'deployment_branch_policy')) {
        Add-AutoFlowFinding $Findings 'BRANCH_POLICY_UNKNOWN' 'UNKNOWN' $Repository $Environment 'A API nao retornou deployment_branch_policy.'
        return
    }
    $policy = $EnvironmentData.deployment_branch_policy
    if ($null -eq $policy) {
        Add-AutoFlowFinding $Findings 'BRANCH_POLICY_UNRESTRICTED' 'INCONSISTENT' $Repository $Environment 'O Environment nao restringe deployments por branch.'
        return
    }
    if (-not (Test-AutoFlowObjectProperty $policy 'protected_branches') -or -not (Test-AutoFlowObjectProperty $policy 'custom_branch_policies') -or $policy.protected_branches -isnot [bool] -or $policy.custom_branch_policies -isnot [bool]) {
        Add-AutoFlowFinding $Findings 'BRANCH_POLICY_INVALID' 'UNKNOWN' $Repository $Environment 'O conteudo de deployment_branch_policy e incompleto.'
        return
    }
    $protectedOnly = [bool]$policy.protected_branches
    $custom = [bool]$policy.custom_branch_policies
    if ($protectedOnly -eq $custom) {
        Add-AutoFlowFinding $Findings 'BRANCH_POLICY_INVALID' 'INCONSISTENT' $Repository $Environment 'A politica deve selecionar protected_branches ou custom_branch_policies.'
        return
    }

    if ($custom) {
        $endpoint = "/repos/$FullName/environments/$Environment/deployment-branch-policies"
        $policies = Get-AutoFlowApiCollection -Endpoint $endpoint -CollectionName 'branch_policies' -ApiInvoker $ApiInvoker
        if (-not $policies.Success) {
            Add-AutoFlowValidationQueryError $QueryErrors $Repository 'deployment_branch_policies' $policies
            Add-AutoFlowFinding $Findings 'BRANCH_POLICY_UNKNOWN' 'UNKNOWN' $Repository $Environment 'Nao foi possivel consultar as branch policies customizadas.'
            return
        }
        if (@($policies.Data | Where-Object { -not (Test-AutoFlowObjectProperty $_ 'name') -or $_.name -isnot [string] }).Count -gt 0) {
            Add-AutoFlowValidationQueryError $QueryErrors $Repository 'deployment_branch_policies' (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Branch policy sem nome valido.')
            Add-AutoFlowFinding $Findings 'BRANCH_POLICY_UNKNOWN' 'UNKNOWN' $Repository $Environment 'A API retornou branch policies incompletas.'
            return
        }
        $matched = @($policies.Data | Where-Object { (Test-AutoFlowObjectProperty $_ 'name') -and [string]$_.name -ceq $ExpectedBranch }).Count -gt 0
        $policyNames = @($policies.Data | Where-Object { Test-AutoFlowObjectProperty $_ 'name' } | ForEach-Object { [string]$_.name })
        if (-not $matched -or $policyNames.Count -ne 1) {
            Add-AutoFlowFinding $Findings 'BRANCH_POLICY_BRANCH_MISMATCH' 'INCONSISTENT' $Repository $Environment "A policy customizada deve permitir somente a branch $ExpectedBranch."
        }
        return
    }

    $branchResponse = & $ApiInvoker "/repos/$FullName/branches/$ExpectedBranch"
    if (-not $branchResponse.Success) {
        Add-AutoFlowValidationQueryError $QueryErrors $Repository "branch:$ExpectedBranch" $branchResponse
        Add-AutoFlowFinding $Findings 'BRANCH_POLICY_UNKNOWN' 'UNKNOWN' $Repository $Environment "Nao foi possivel confirmar a existencia/protecao da branch $ExpectedBranch ($($branchResponse.ErrorKind)); 404 nao e tratado como ausencia confirmada."
        return
    }
    if (-not (Test-AutoFlowObjectProperty $branchResponse.Data 'name') -or $branchResponse.Data.name -isnot [string] -or $branchResponse.Data.name -cne $ExpectedBranch -or -not (Test-AutoFlowObjectProperty $branchResponse.Data 'protected') -or $branchResponse.Data.protected -isnot [bool]) {
        Add-AutoFlowFinding $Findings 'BRANCH_POLICY_INVALID_RESPONSE' 'UNKNOWN' $Repository $Environment 'A API retornou dados incompletos para a branch.'
        return
    }
    if (-not [bool]$branchResponse.Data.protected) {
        Add-AutoFlowFinding $Findings 'BRANCH_NOT_PROTECTED' 'INCONSISTENT' $Repository $Environment "A policy permite apenas branches protegidas; $ExpectedBranch nao esta protegida."
    }
    if ($OtherEnvironmentBranch) {
        $otherResponse = & $ApiInvoker "/repos/$FullName/branches/$OtherEnvironmentBranch"
        if (-not $otherResponse.Success) {
            Add-AutoFlowValidationQueryError $QueryErrors $Repository "branch:$OtherEnvironmentBranch" $otherResponse
            Add-AutoFlowFinding $Findings 'BRANCH_POLICY_ISOLATION_UNKNOWN' 'UNKNOWN' $Repository $Environment 'Nao foi possivel verificar se a policy protected_branches tambem aceita a branch do outro Environment.'
        } elseif (-not (Test-AutoFlowObjectProperty $otherResponse.Data 'protected') -or $otherResponse.Data.protected -isnot [bool] -or -not (Test-AutoFlowObjectProperty $otherResponse.Data 'name') -or $otherResponse.Data.name -isnot [string] -or $otherResponse.Data.name -cne $OtherEnvironmentBranch) {
            Add-AutoFlowFinding $Findings 'BRANCH_POLICY_ISOLATION_UNKNOWN' 'UNKNOWN' $Repository $Environment 'A API retornou dados incompletos para a branch do outro Environment.'
        } elseif ([bool]$otherResponse.Data.protected) {
            Add-AutoFlowFinding $Findings 'BRANCH_POLICY_CROSSES_ENVIRONMENTS' 'INCONSISTENT' $Repository $Environment "A policy protected_branches tambem permite a branch $OtherEnvironmentBranch do outro Environment."
        }
    }
}

function Get-AutoFlowEnvironmentSnapshot {
    param(
        $RepositoryConfig,
        [string]$Environment,
        [scriptblock]$ApiInvoker,
        [System.Collections.Generic.List[object]]$Findings,
        [System.Collections.Generic.List[object]]$QueryErrors
    )

    $fullName = $RepositoryConfig.FullName
    $snapshot = [ordered]@{
        Repository = $RepositoryConfig.Name
        FullName = $fullName
        Environment = $Environment
        Branch = $RepositoryConfig.Branches[$Environment]
        State = 'UNKNOWN'
        VariablesState = 'UNKNOWN'
        SecretsState = 'UNKNOWN'
        Variables = @{}
        SecretNames = @()
    }

    $environmentResponse = & $ApiInvoker "/repos/$fullName/environments/$Environment"
    if (-not $environmentResponse.Success) {
        $snapshot.State = $environmentResponse.ErrorKind
        Add-AutoFlowValidationQueryError $QueryErrors $RepositoryConfig.Name "environment:$Environment" $environmentResponse
        Add-AutoFlowFinding $Findings 'ENVIRONMENT_UNKNOWN' 'UNKNOWN' $RepositoryConfig.Name $Environment "Nao foi possivel consultar o Environment ($($environmentResponse.ErrorKind)); ausencia so e confirmada por inventario valido."
        return [pscustomobject]$snapshot
    }
    if (-not (Test-AutoFlowObjectProperty $environmentResponse.Data 'name') -or $environmentResponse.Data.name -isnot [string] -or $environmentResponse.Data.name -cne $Environment) {
        $snapshot.State = 'INVALID_RESPONSE'
        Add-AutoFlowValidationQueryError $QueryErrors $RepositoryConfig.Name "environment:$Environment" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Environment retornado nao corresponde ao solicitado.')
        Add-AutoFlowFinding $Findings 'ENVIRONMENT_UNKNOWN' 'UNKNOWN' $RepositoryConfig.Name $Environment 'A API retornou um Environment inesperado.'
        return [pscustomobject]$snapshot
    }
    $snapshot.State = 'FOUND'
    $otherEnvironment = if ($Environment -eq 'homolog') { 'production' } else { 'homolog' }
    $otherBranch = $RepositoryConfig.Branches[$otherEnvironment]
    Test-AutoFlowEnvironmentProtection $environmentResponse.Data $snapshot.Branch $otherBranch $RepositoryConfig.Name $fullName $Environment $ApiInvoker $Findings $QueryErrors

    $variablesResponse = Get-AutoFlowApiCollection -Endpoint "/repos/$fullName/environments/$Environment/variables" -CollectionName 'variables' -PerPage 30 -ApiInvoker $ApiInvoker
    if (-not $variablesResponse.Success) {
        $snapshot.VariablesState = $variablesResponse.ErrorKind
        Add-AutoFlowValidationQueryError $QueryErrors $RepositoryConfig.Name "variables:$Environment" $variablesResponse
        Add-AutoFlowFinding $Findings 'VARIABLES_UNKNOWN' 'UNKNOWN' $RepositoryConfig.Name $Environment "Nao foi possivel consultar as Variables ($($variablesResponse.ErrorKind)); nenhuma foi considerada ausente."
    } else {
        $variables = @{}
        $invalid = $false
        foreach ($variable in @($variablesResponse.Data)) {
            if (-not (Test-AutoFlowObjectProperty $variable 'name') -or $variable.name -isnot [string] -or -not (Test-AutoFlowObjectProperty $variable 'value') -or $variable.value -isnot [string]) {
                $invalid = $true
                break
            }
            $variables[[string]$variable.name] = [string]$variable.value
        }
        if ($invalid) {
            $snapshot.VariablesState = 'INVALID_RESPONSE'
            Add-AutoFlowValidationQueryError $QueryErrors $RepositoryConfig.Name "variables:$Environment" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Variable sem nome ou valor.')
            Add-AutoFlowFinding $Findings 'VARIABLES_UNKNOWN' 'UNKNOWN' $RepositoryConfig.Name $Environment 'A API retornou Variables incompletas.'
        } else {
            $snapshot.VariablesState = 'OK'
            $snapshot.Variables = $variables
        }
    }

    $secretsResponse = Get-AutoFlowApiCollection -Endpoint "/repos/$fullName/environments/$Environment/secrets" -CollectionName 'secrets' -ApiInvoker $ApiInvoker
    if (-not $secretsResponse.Success) {
        $snapshot.SecretsState = $secretsResponse.ErrorKind
        Add-AutoFlowValidationQueryError $QueryErrors $RepositoryConfig.Name "secret_names:$Environment" $secretsResponse
        Add-AutoFlowFinding $Findings 'SECRETS_UNKNOWN' 'UNKNOWN' $RepositoryConfig.Name $Environment "Nao foi possivel consultar os nomes dos Secrets ($($secretsResponse.ErrorKind)); nenhum foi considerado ausente."
    } else {
        $secretNames = New-Object System.Collections.Generic.List[string]
        $invalid = $false
        foreach ($secret in @($secretsResponse.Data)) {
            if (-not (Test-AutoFlowObjectProperty $secret 'name') -or $secret.name -isnot [string]) {
                $invalid = $true
                break
            }
            [void]$secretNames.Add([string]$secret.name)
        }
        if ($invalid) {
            $snapshot.SecretsState = 'INVALID_RESPONSE'
            Add-AutoFlowValidationQueryError $QueryErrors $RepositoryConfig.Name "secret_names:$Environment" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Secret sem nome.')
            Add-AutoFlowFinding $Findings 'SECRETS_UNKNOWN' 'UNKNOWN' $RepositoryConfig.Name $Environment 'A API retornou nomes de Secrets incompletos.'
        } else {
            $snapshot.SecretsState = 'OK'
            $snapshot.SecretNames = @($secretNames.ToArray())
        }
    }

    if ($snapshot.VariablesState -eq 'OK') {
        foreach ($name in $RepositoryConfig.RequiredVariables) {
            if (-not $snapshot.Variables.ContainsKey($name)) {
                Add-AutoFlowFinding $Findings 'MISSING_VARIABLE' 'INCONSISTENT' $RepositoryConfig.Name $Environment "Variable obrigatoria ausente: $name."
            } elseif ([string]::IsNullOrWhiteSpace([string]$snapshot.Variables[$name])) {
                Add-AutoFlowFinding $Findings 'EMPTY_VARIABLE' 'INCONSISTENT' $RepositoryConfig.Name $Environment "Variable obrigatoria sem valor: $name."
            }
        }
        if ($snapshot.Variables.ContainsKey('TERRAFORM_APPLY_APPROVAL_CONFIGURED') -and $snapshot.Variables['TERRAFORM_APPLY_APPROVAL_CONFIGURED'] -cne 'true') {
            Add-AutoFlowFinding $Findings 'APPROVAL_MARKER_NOT_TRUE' 'INCONSISTENT' $RepositoryConfig.Name $Environment 'TERRAFORM_APPLY_APPROVAL_CONFIGURED nao esta definido exatamente como true.'
        }
        if ($snapshot.Variables.ContainsKey('AWS_EXPECTED_ACCOUNT_ID') -and $snapshot.Variables['AWS_EXPECTED_ACCOUNT_ID'] -notmatch '^[0-9]{12}$') {
            Add-AutoFlowFinding $Findings 'AWS_ACCOUNT_FORMAT_INVALID' 'INCONSISTENT' $RepositoryConfig.Name $Environment 'AWS_EXPECTED_ACCOUNT_ID nao tem 12 digitos.'
        }
        if ($snapshot.Variables.ContainsKey('AWS_REGION') -and $snapshot.Variables['AWS_REGION'] -notmatch '^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$') {
            Add-AutoFlowFinding $Findings 'AWS_REGION_FORMAT_INVALID' 'INCONSISTENT' $RepositoryConfig.Name $Environment 'AWS_REGION tem formato invalido.'
        }
        if ($snapshot.Variables.ContainsKey('API_GATEWAY_CORS_ORIGINS') -and -not (Test-AutoFlowCorsValue $snapshot.Variables['API_GATEWAY_CORS_ORIGINS'])) {
            Add-AutoFlowFinding $Findings 'CORS_VALUE_INVALID' 'INCONSISTENT' $RepositoryConfig.Name $Environment 'API_GATEWAY_CORS_ORIGINS nao e um array JSON de strings.'
        }
        if ($snapshot.Variables.ContainsKey('NEW_RELIC_REGION') -and $snapshot.Variables['NEW_RELIC_REGION'] -notin @('US', 'EU')) {
            Add-AutoFlowFinding $Findings 'NEW_RELIC_REGION_INVALID' 'INCONSISTENT' $RepositoryConfig.Name $Environment 'NEW_RELIC_REGION deve ser US ou EU.'
        }
    }
    if ($snapshot.SecretsState -eq 'OK') {
        $requiredSecrets = @($RepositoryConfig.RequiredSecrets)
        if ($snapshot.VariablesState -eq 'OK' -and $snapshot.Variables.ContainsKey('ENABLE_NEWRELIC_APM') -and $snapshot.Variables['ENABLE_NEWRELIC_APM'] -ceq 'true') {
            $requiredSecrets += 'NEW_RELIC_LICENSE_KEY'
        }
        foreach ($name in $requiredSecrets) {
            if ($snapshot.SecretNames -notcontains $name) {
                Add-AutoFlowFinding $Findings 'MISSING_SECRET' 'INCONSISTENT' $RepositoryConfig.Name $Environment "Nome de Secret obrigatorio ausente: $name."
            }
        }
    }
    return [pscustomobject]$snapshot
}

function Get-AutoFlowStateContractInput {
    param(
        [hashtable]$Snapshots,
        [System.Collections.Generic.List[object]]$Findings,
        [string[]]$Environments
    )

    $roots = @(Get-AutoFlowStateRoots)
    $documentEnvironments = @{}
    $complete = $true
    foreach ($environment in $Environments) {
        $environmentRoots = @{}
        foreach ($root in $roots) {
            $snapshotKey = "$($root.Repository)|$environment"
            if (-not $Snapshots.ContainsKey($snapshotKey) -or $Snapshots[$snapshotKey].VariablesState -ne 'OK') {
                $complete = $false
                continue
            }
            $variables = $Snapshots[$snapshotKey].Variables
            $requiredNames = @('AWS_EXPECTED_ACCOUNT_ID', 'AWS_TERRAFORM_STATE_BUCKET', 'AWS_REGION', $root.KeyVariable)
            $missing = @($requiredNames | Where-Object { -not $variables.ContainsKey($_) -or [string]::IsNullOrWhiteSpace([string]$variables[$_]) })
            if ($missing.Count -gt 0) {
                $complete = $false
                continue
            }
            $rootConfig = @{
                account_id = [string]$variables['AWS_EXPECTED_ACCOUNT_ID']
                bucket = [string]$variables['AWS_TERRAFORM_STATE_BUCKET']
                region = [string]$variables['AWS_REGION']
                key = [string]$variables[$root.KeyVariable]
            }
            $consumes = @{}
            foreach ($producer in @($root.ConsumeVariables.Keys)) {
                $variableName = [string]$root.ConsumeVariables[$producer]
                if (-not $variables.ContainsKey($variableName) -or [string]::IsNullOrWhiteSpace([string]$variables[$variableName])) {
                    $complete = $false
                } else {
                    $consumes[$producer] = [string]$variables[$variableName]
                }
            }
            foreach ($producer in @($root.ConsumeDefaults.Keys)) {
                $consumes[$producer] = [string]$root.ConsumeDefaults[$producer]
            }
            if ($consumes.Count -gt 0) { $rootConfig['consumes'] = $consumes }
            $environmentRoots[$root.Name] = $rootConfig
        }
        $documentEnvironments[$environment] = @{ roots = $environmentRoots }
    }
    if (-not $complete) { return [pscustomobject]@{ Complete = $false; Document = $null } }
    return [pscustomobject]@{ Complete = $true; Document = @{ environments = $documentEnvironments } }
}

function Invoke-AutoFlowStateContract {
    param([hashtable]$Document)

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        return [pscustomobject]@{ State = 'UNKNOWN'; Message = 'Python nao foi encontrado; contrato de State nao executado.' }
    }
    $contractPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'terraform_state_contract.py'
    if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) {
        return [pscustomobject]@{ State = 'UNKNOWN'; Message = 'terraform_state_contract.py nao encontrado.' }
    }

    $temporaryPath = [System.IO.Path]::GetTempFileName()
    try {
        $json = ConvertTo-Json -InputObject $Document -Depth 20
        [System.IO.File]::WriteAllText($temporaryPath, $json, (New-Object System.Text.UTF8Encoding($false)))
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $python.Source
        $startInfo.Arguments = '"{0}" "{1}"' -f $contractPath, $temporaryPath
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $startInfo.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        try {
            if (-not $process.Start()) {
                return [pscustomobject]@{ State = 'UNKNOWN'; Message = 'Nao foi possivel iniciar o validador Python.' }
            }
            $stdoutTask = $process.StandardOutput.ReadToEndAsync()
            $stderrTask = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit(20000)) {
                try { $process.Kill() } catch { }
                return [pscustomobject]@{ State = 'UNKNOWN'; Message = 'Validador Python excedeu 20 segundos.' }
            }
            $process.WaitForExit()
            if ($process.ExitCode -eq 0) {
                return [pscustomobject]@{ State = 'VALID'; Message = 'Contrato dos seis Terraform roots validado para os dois Environments.' }
            }
            $errorText = $stderrTask.Result
            $message = 'O terraform_state_contract.py rejeitou o contrato de State.'
            if ($errorText -match 'Conta, bucket e') { $message = 'Conta, bucket ou regiao divergem entre roots do mesmo Environment.' }
            elseif ($errorText -match 'Key fora do prefixo') { $message = 'Uma State Key nao usa o prefixo exigido para o Environment.' }
            elseif ($errorText -match 'seis keys devem ser') { $message = 'Duas ou mais State Keys do mesmo Environment estao duplicadas.' }
            elseif ($errorText -match 'podem compartilhar keys de State') { $message = 'Homolog e production compartilham uma State Key.' }
            elseif ($errorText -match 'key consumida') { $message = 'Uma State Key consumida diverge da State Key do root produtor.' }
            elseif ($errorText -match 'de State ausentes') { $message = 'Uma referencia de State consumida esta ausente ou inesperada.' }
            elseif ($errorText -match 'seis Terraform roots') { $message = 'A matriz dos seis Terraform roots esta incompleta.' }
            return [pscustomobject]@{ State = 'INCONSISTENT'; Message = $message }
        } finally {
            $process.Dispose()
        }
    } catch {
        return [pscustomobject]@{ State = 'UNKNOWN'; Message = 'Falha local ao executar o contrato Terraform.' }
    } finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-AutoFlowValidation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidateSet('homolog', 'production')][string]$Environment,
        [scriptblock]$ApiInvoker = ${function:Invoke-AutoFlowGitHubApi}
    )

    $findings = New-Object System.Collections.Generic.List[object]
    $queryErrors = New-Object System.Collections.Generic.List[object]
    $repositories = @(Get-AutoFlowRepositories)
    $snapshots = @{}

    foreach ($repository in $repositories) {
        $repoResponse = & $ApiInvoker "/repos/$($repository.FullName)"
        if (-not $repoResponse.Success) {
            if ($repoResponse.ErrorKind -eq 'NOT_FOUND') {
                Add-AutoFlowFinding $findings 'REPOSITORY_NOT_FOUND_OR_NOT_VISIBLE' 'UNKNOWN' $repository.Name '' 'GitHub retornou 404; repositorio ausente e repositorio privado sem acesso nao podem ser distinguidos por esta resposta.'
            } else {
                Add-AutoFlowValidationQueryError $queryErrors $repository.Name 'repository' $repoResponse
                Add-AutoFlowFinding $findings 'REPOSITORY_UNKNOWN' 'UNKNOWN' $repository.Name '' "Nao foi possivel consultar o repositorio ($($repoResponse.ErrorKind))."
            }
            continue
        }
        if (-not (Test-AutoFlowObjectProperty $repoResponse.Data 'full_name') -or [string]$repoResponse.Data.full_name -ine $repository.FullName) {
            Add-AutoFlowValidationQueryError $queryErrors $repository.Name 'repository' (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Repositorio retornado invalido.')
            Add-AutoFlowFinding $findings 'REPOSITORY_UNKNOWN' 'UNKNOWN' $repository.Name '' 'A API retornou metadados de repositorio invalidos.'
            continue
        }
        $environmentInventory = Get-AutoFlowApiCollection -Endpoint "/repos/$($repository.FullName)/environments" -CollectionName 'environments' -ApiInvoker $ApiInvoker
        if (-not $environmentInventory.Success) {
            Add-AutoFlowValidationQueryError $queryErrors $repository.Name 'environment_inventory' $environmentInventory
            foreach ($environmentName in (Get-AutoFlowEnvironmentNames)) {
                Add-AutoFlowFinding $findings 'ENVIRONMENT_UNKNOWN' 'UNKNOWN' $repository.Name $environmentName "Nao foi possivel inventariar Environments ($($environmentInventory.ErrorKind)); nao se presume ausencia."
                $snapshots["$($repository.Name)|$environmentName"] = [pscustomobject]@{
                    Repository = $repository.Name; FullName = $repository.FullName; Environment = $environmentName
                    Branch = $repository.Branches[$environmentName]; State = 'UNKNOWN'
                    VariablesState = 'UNKNOWN'; SecretsState = 'UNKNOWN'; Variables = @{}; SecretNames = @()
                }
            }
            continue
        }
        $environmentNames = New-Object System.Collections.Generic.List[string]
        $invalidEnvironmentInventory = $false
        foreach ($environmentEntry in @($environmentInventory.Data)) {
            if (-not (Test-AutoFlowObjectProperty $environmentEntry 'name')) {
                $invalidEnvironmentInventory = $true
                break
            }
            [void]$environmentNames.Add([string]$environmentEntry.name)
        }
        if ($invalidEnvironmentInventory) {
            Add-AutoFlowValidationQueryError $queryErrors $repository.Name 'environment_inventory' (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Environment sem nome.')
            foreach ($environmentName in (Get-AutoFlowEnvironmentNames)) {
                Add-AutoFlowFinding $findings 'ENVIRONMENT_UNKNOWN' 'UNKNOWN' $repository.Name $environmentName 'A API retornou um inventario de Environments invalido.'
                $snapshots["$($repository.Name)|$environmentName"] = [pscustomobject]@{
                    Repository = $repository.Name; FullName = $repository.FullName; Environment = $environmentName
                    Branch = $repository.Branches[$environmentName]; State = 'INVALID_RESPONSE'
                    VariablesState = 'UNKNOWN'; SecretsState = 'UNKNOWN'; Variables = @{}; SecretNames = @()
                }
            }
            continue
        }
        foreach ($environmentName in (Get-AutoFlowEnvironmentNames)) {
            if ($environmentNames -notcontains $environmentName) {
                Add-AutoFlowFinding $findings 'MISSING_ENVIRONMENT' 'INCONSISTENT' $repository.Name $environmentName 'O inventario valido da API nao contem este GitHub Environment.'
                $snapshots["$($repository.Name)|$environmentName"] = [pscustomobject]@{
                    Repository = $repository.Name; FullName = $repository.FullName; Environment = $environmentName
                    Branch = $repository.Branches[$environmentName]; State = 'MISSING'
                    VariablesState = 'UNKNOWN'; SecretsState = 'UNKNOWN'; Variables = @{}; SecretNames = @()
                }
            } else {
                $snapshot = Get-AutoFlowEnvironmentSnapshot $repository $environmentName $ApiInvoker $findings $queryErrors
                $snapshots["$($repository.Name)|$environmentName"] = $snapshot
            }
        }
    }

    $contractInput = Get-AutoFlowStateContractInput $snapshots $findings (Get-AutoFlowEnvironmentNames)
    if ($contractInput.Complete) {
        $contractResult = Invoke-AutoFlowStateContract $contractInput.Document
        if ($contractResult.State -eq 'INCONSISTENT') {
            Add-AutoFlowFinding $findings 'TERRAFORM_STATE_CONTRACT_INVALID' 'INCONSISTENT' 'all' '' $contractResult.Message
        } elseif ($contractResult.State -eq 'UNKNOWN') {
            Add-AutoFlowFinding $findings 'TERRAFORM_STATE_CONTRACT_UNKNOWN' 'UNKNOWN' 'all' '' $contractResult.Message
        }
    } else {
        $contractResult = [pscustomobject]@{ State = 'NOT_RUN_INCOMPLETE_INPUT'; Message = 'Contrato de State nao executado porque faltam dados consultaveis; ausencia e acesso indisponivel permanecem estados distintos.' }
    }

    $inconsistent = @($findings | Where-Object { $_.State -eq 'INCONSISTENT' }).Count -gt 0
    $unknown = @($findings | Where-Object { $_.State -eq 'UNKNOWN' }).Count -gt 0
    return [pscustomobject]@{
        Environment = $Environment
        EnvironmentsChecked = @(Get-AutoFlowEnvironmentNames)
        Repositories = @($repositories | ForEach-Object {
            $repo = $_
            [pscustomobject]@{
                Name = $repo.Name
                FullName = $repo.FullName
                Environments = @((Get-AutoFlowEnvironmentNames) | ForEach-Object { $snapshots["$($repo.Name)|$_"] })
            }
        })
        StateContract = $contractResult
        Findings = @($findings.ToArray())
        QueryErrors = @($queryErrors.ToArray())
        HasInconsistencies = $inconsistent
        HasUnknown = $unknown
        HasQueryErrors = ($queryErrors.Count -gt 0)
    }
}

Export-ModuleMember -Function Invoke-AutoFlowValidation, Invoke-AutoFlowStateContract, Get-AutoFlowStateContractInput, Test-AutoFlowEnvironmentProtection
