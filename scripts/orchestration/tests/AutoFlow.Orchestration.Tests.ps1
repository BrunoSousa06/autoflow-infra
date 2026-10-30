$script:OrchestrationPath = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $script:OrchestrationPath 'AutoFlow.Config.psm1') -Force
Import-Module (Join-Path $script:OrchestrationPath 'AutoFlow.GitHub.psm1') -Force
Import-Module (Join-Path $script:OrchestrationPath 'AutoFlow.Validation.psm1') -Force
Import-Module (Join-Path $script:OrchestrationPath 'AutoFlow.Reporting.psm1') -Force

function New-StatusApiMock {
    $requestList = New-Object System.Collections.Generic.List[string]
    $resultFactory = {
        param($Data)
        $dataObject = ConvertFrom-Json -InputObject (ConvertTo-Json -InputObject $Data -Depth 30) -ErrorAction Stop
        [pscustomobject]@{ Success = $true; StatusCode = 200; Data = $dataObject; ErrorKind = ''; Message = ''; Headers = @{} }
    }.GetNewClosure()
    $script:MockRequests = $requestList
    return {
        param($Endpoint)
        [void]$requestList.Add($Endpoint)
        if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)$') {
            return (& $resultFactory @{ full_name = $matches[1] })
        }
        if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)/branches/([^?]+)') {
            return (& $resultFactory @{ name = $matches[2]; protected = $true })
        }
        if ($Endpoint -match '/actions/workflows\?') {
            return (& $resultFactory @{ total_count = 1; workflows = @(@{ id = 55; name = 'Pipeline'; state = 'active' }) })
        }
        if ($Endpoint -match '/actions/workflows/55/runs\?') {
            $repo = [regex]::Match($Endpoint, '/repos/(autoflow-fiap/[^/]+)/').Groups[1].Value
            $branch = if ($Endpoint -match 'branch=main') { 'main' } else { 'develop' }
            $repoName = ($repo -split '/')[-1]
            $statusByRepository = @{ 'autoflow-infra' = 'waiting'; 'autoflow-db' = 'queued'; 'autoflow-lambda' = 'in_progress'; 'autoflow' = 'completed' }
            $runStatus = $statusByRepository[$repoName]
            $runConclusion = if ($runStatus -eq 'completed') { 'success' } else { $null }
            return (& $resultFactory @{ total_count = 1; workflow_runs = @(@{
                id = 500
                status = $runStatus
                conclusion = $runConclusion
                head_branch = $branch
                head_sha = 'abcdef0123456789abcdef0123456789abcdef01'
                html_url = "https://github.com/$repo/actions/runs/500"
                created_at = '2026-10-30T12:00:00Z'
            }) })
        }
        if ($Endpoint -match '/actions/runs/500/jobs\?') {
            $repo = [regex]::Match($Endpoint, '/repos/(autoflow-fiap/[^/]+)/').Groups[1].Value
            return (& $resultFactory @{ total_count = 4; jobs = @(
                @{ id = 1; name = 'failed job'; status = 'completed'; conclusion = 'failure'; html_url = "https://github.com/$repo/actions/runs/500/job/1" },
                @{ id = 2; name = 'cancelled job'; status = 'completed'; conclusion = 'cancelled'; html_url = "https://github.com/$repo/actions/runs/500/job/2" },
                @{ id = 3; name = 'skipped job'; status = 'completed'; conclusion = 'skipped'; html_url = "https://github.com/$repo/actions/runs/500/job/3" },
                @{ id = 4; name = 'waiting job'; status = 'waiting'; conclusion = $null; html_url = "https://github.com/$repo/actions/runs/500/job/4" }
             ) })
        }
        if ($Endpoint -match '/actions/runs/500/pending_deployments$') {
            return [pscustomobject]@{
                Success = $true; StatusCode = 200; ErrorKind = ''; Message = ''; Headers = @{}
                Data = @([pscustomobject]@{
                    environment = [pscustomobject]@{ name = 'homolog' }
                    reviewers = @([pscustomobject]@{ type = 'User' })
                    current_user_can_approve = $true
                })
            }
        }
        return [pscustomobject]@{ Success = $false; StatusCode = 404; Data = $null; ErrorKind = 'NOT_FOUND'; Message = 'mock'; Headers = @{} }
    }.GetNewClosure()
}

function New-SyntheticStateContract {
    $allRoots = @('vpc_eks', 'rds', 'lambda', 'application', 'api_gateway', 'newrelic')
    $documentEnvironments = @{}
    foreach ($environmentName in @('homolog', 'production')) {
        $roots = @{}
        foreach ($rootName in $allRoots) {
            $suffix = if ($environmentName -eq 'homolog') { '1' } else { '2' }
            $roots[$rootName] = @{
                account_id = ($suffix * 12)
                bucket = "autoflow-$environmentName-state"
                region = 'us-east-1'
                key = "$environmentName/state/$rootName.tfstate"
            }
        }
        $roots.rds.consumes = @{ vpc_eks = $roots.vpc_eks.key }
        $roots.lambda.consumes = @{ vpc_eks = $roots.vpc_eks.key; rds = $roots.rds.key }
        $roots.application.consumes = @{ rds = $roots.rds.key }
        $roots.api_gateway.consumes = @{ vpc_eks = $roots.vpc_eks.key }
        $roots.newrelic.consumes = @{ vpc_eks = $roots.vpc_eks.key }
        $documentEnvironments[$environmentName] = @{ roots = $roots }
    }
    return @{ environments = $documentEnvironments }
}

function New-ValidationApiMock {
    param([string]$ApprovalMarker = 'true')
    $requestList = New-Object System.Collections.Generic.List[string]
    $variableMap = @{}
    $resultFactory = {
        param($Data)
        $dataObject = ConvertFrom-Json -InputObject (ConvertTo-Json -InputObject $Data -Depth 30) -ErrorAction Stop
        [pscustomobject]@{ Success = $true; StatusCode = 200; Data = $dataObject; ErrorKind = ''; Message = ''; Headers = @{} }
    }.GetNewClosure()
    $script:MockRequests = $requestList
    $script:ValidationVariables = $variableMap
    $repositories = @(Get-AutoFlowRepositories)
    $roots = @(Get-AutoFlowStateRoots)
    foreach ($environmentName in @('homolog', 'production')) {
        $environmentRoots = @{}
        foreach ($root in $roots) {
            $environmentRoots[$root.Name] = "$environmentName/state/$($root.Name).tfstate"
        }
        foreach ($repository in $repositories) {
            $values = @{}
            foreach ($name in $repository.RequiredVariables) { $values[$name] = 'synthetic' }
            $account = if ($environmentName -eq 'homolog') { '1' * 12 } else { '2' * 12 }
            $values['AWS_EXPECTED_ACCOUNT_ID'] = $account
            $values['AWS_REGION'] = 'us-east-1'
            $values['AWS_TERRAFORM_STATE_BUCKET'] = "autoflow-$environmentName-state"
            $values['TERRAFORM_APPLY_APPROVAL_CONFIGURED'] = $ApprovalMarker
            if ($repository.Name -eq 'autoflow-infra') {
                $values['AWS_TF_STATE_KEY_INFRA'] = $environmentRoots.vpc_eks
                $values['AWS_TF_STATE_KEY_GATEWAY'] = $environmentRoots.api_gateway
                $values['AWS_TF_STATE_KEY_NEWRELIC'] = $environmentRoots.newrelic
                $values['API_GATEWAY_CORS_ORIGINS'] = '[]'
                $values['NEW_RELIC_REGION'] = 'US'
            } elseif ($repository.Name -eq 'autoflow-db') {
                $values['AWS_TF_STATE_KEY'] = $environmentRoots.rds
                $values['AWS_INFRA_STATE_KEY'] = $environmentRoots.vpc_eks
            } elseif ($repository.Name -eq 'autoflow-lambda') {
                $values['AWS_TF_STATE_KEY'] = $environmentRoots.lambda
                $values['AWS_INFRA_STATE_KEY'] = $environmentRoots.vpc_eks
                $values['AWS_RDS_STATE_KEY'] = $environmentRoots.rds
                $values['AWS_LAMBDA_EXECUTION_ROLE_ARN'] = "arn:aws:iam::$account:role/synthetic"
            } else {
                $values['AWS_TF_STATE_KEY'] = $environmentRoots.application
                $values['AWS_RDS_STATE_KEY'] = $environmentRoots.rds
                $values['API_GATEWAY_CORS_ORIGINS'] = '[]'
            }
            $variableMap["$($repository.Name)|$environmentName"] = $values
        }
    }
    return {
        param($Endpoint)
        [void]$requestList.Add($Endpoint)
        if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)$') {
            return (& $resultFactory @{ full_name = $matches[1] })
        }
        if ($Endpoint -match '/environments\?per_page=100') {
            return (& $resultFactory @{ total_count = 2; environments = @(@{ name = 'homolog' }, @{ name = 'production' }) })
        }
        if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)/environments/(homolog|production)(\?|$)') {
            return (& $resultFactory @{
                name = $matches[2]
                protection_rules = @(@{ type = 'required_reviewers'; reviewers = @(@{ type = 'User' }) })
                deployment_branch_policy = @{ protected_branches = $false; custom_branch_policies = $true }
            })
        }
        if ($Endpoint -match '/environments/(homolog|production)/deployment-branch-policies\?') {
            $environmentName = $matches[1]
            $branchName = if ($environmentName -eq 'homolog') { 'develop' } else { 'main' }
            return (& $resultFactory @{ total_count = 1; branch_policies = @(@{ name = $branchName; type = 'branch' }) })
        }
        if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)/branches/([^?]+)') {
            return (& $resultFactory @{ name = $matches[2]; protected = $true })
        }
        if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)/environments/(homolog|production)/variables\?') {
            $repoName = ($matches[1] -split '/')[-1]
            $environmentName = $matches[2]
            $values = $variableMap["$repoName|$environmentName"]
            $items = @($values.Keys | ForEach-Object { @{ name = $_; value = $values[$_] } })
            return (& $resultFactory @{ total_count = $items.Count; variables = $items })
        }
        if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)/environments/(homolog|production)/secrets\?') {
            $repoName = ($matches[1] -split '/')[-1]
            $environmentName = $matches[2]
            $repositoryConfig = @(Get-AutoFlowRepositories | Where-Object { $_.Name -eq $repoName })[0]
            $names = @($repositoryConfig.RequiredSecrets | ForEach-Object { @{ name = $_ } })
            return (& $resultFactory @{ total_count = $names.Count; secrets = $names })
        }
        return [pscustomobject]@{ Success = $false; StatusCode = 404; Data = $null; ErrorKind = 'NOT_FOUND'; Message = 'mock'; Headers = @{} }
    }.GetNewClosure()
}

Describe 'AutoFlow Pipeline Orchestrator' {
    It 'limits repository queries to the four configured repositories' {
        $repositories = @(Get-AutoFlowRepositories)
        $repositories.Count | Should Be 4
        @($repositories | Where-Object { $_.FullName -notmatch '^autoflow-fiap/autoflow(-infra|-db|-lambda)?$' }).Count | Should Be 0
    }

    It 'classifies permission, rate limit, missing resource, unavailable API and malformed JSON' {
        $access = ConvertFrom-AutoFlowGhResponse -ExitCode 1 -StandardOutput ("HTTP/2.0 403 Forbidden`r`nX-RateLimit-Remaining: 10`r`n`r`n{" + '"message":"denied"' + '}')
        $rate = ConvertFrom-AutoFlowGhResponse -ExitCode 1 -StandardOutput ("HTTP/2.0 403 Forbidden`r`nX-RateLimit-Remaining: 0`r`n`r`n{" + '"message":"limited"' + '}')
        $missing = ConvertFrom-AutoFlowGhResponse -ExitCode 1 -StandardOutput ("HTTP/2.0 404 Not Found`r`n`r`n{" + '"message":"missing"' + '}')
        $unavailable = ConvertFrom-AutoFlowGhResponse -ExitCode 1 -StandardOutput ("HTTP/2.0 503 Service Unavailable`r`n`r`n{}");
        $tooManyRequests = ConvertFrom-AutoFlowGhResponse -ExitCode 1 -StandardOutput ("HTTP/2.0 429 Too Many Requests`r`n`r`n{}")
        $success = ConvertFrom-AutoFlowGhResponse -ExitCode 0 -StandardOutput ("HTTP/2.0 200 OK`r`nContent-Type: application/json`r`n`r`n{" + '"ok":true' + '}')
        $arrayResponse = ConvertFrom-AutoFlowGhResponse -ExitCode 0 -StandardOutput ("HTTP/2.0 200 OK`r`n`r`n[{" + '"state":"pending"' + '}]')
        $emptyArrayResponse = ConvertFrom-AutoFlowGhResponse -ExitCode 0 -StandardOutput ("HTTP/2.0 200 OK`r`n`r`n[]")
        $invalid = ConvertFrom-AutoFlowGhResponse -ExitCode 0 -StandardOutput ("HTTP/2.0 200 OK`r`n`r`nnot-json")
        $access.ErrorKind | Should Be 'ACCESS_DENIED'
        $rate.ErrorKind | Should Be 'RATE_LIMIT'
        $missing.ErrorKind | Should Be 'NOT_FOUND_OR_NOT_VISIBLE'
        $unavailable.ErrorKind | Should Be 'API_UNAVAILABLE'
        $tooManyRequests.ErrorKind | Should Be 'RATE_LIMIT'
        $success.Success | Should Be $true
        $success.Data.ok | Should Be $true
        ($arrayResponse.Data -is [System.Array]) | Should Be $true
        @($arrayResponse.Data).Count | Should Be 1
        ($emptyArrayResponse.Data -is [System.Array]) | Should Be $true
        @($emptyArrayResponse.Data).Count | Should Be 0
        $invalid.ErrorKind | Should Be 'INVALID_RESPONSE'
    }

    It 'validates collection shape and follows complete pagination' {
        $pageList = New-Object System.Collections.Generic.List[string]
        $script:pages = $pageList
        $resultFactory = {
            param($Data)
            [pscustomobject]@{ Success = $true; StatusCode = 200; Data = [pscustomobject]$Data; ErrorKind = ''; Message = ''; Headers = @{} }
        }.GetNewClosure()
        $transport = {
            param($Endpoint)
            [void]$pageList.Add($Endpoint)
            if ($Endpoint -match 'page=1') {
                return (& $resultFactory @{ total_count = 2; workflows = @(@{ id = 1 }) })
            }
            return (& $resultFactory @{ total_count = 2; workflows = @(@{ id = 2 }) })
        }.GetNewClosure()
        $collection = Get-AutoFlowApiCollection -Endpoint '/repos/autoflow-fiap/autoflow-infra/actions/workflows' -CollectionName 'workflows' -ApiInvoker $transport
        $collection.Success | Should Be $true
        @($collection.Data).Count | Should Be 2
        $pageList.Count | Should Be 2

        $badTransport = { param($Endpoint) [pscustomobject]@{ Success = $true; StatusCode = 200; Data = [pscustomobject]@{ total_count = 0; items = @() }; ErrorKind = ''; Message = ''; Headers = @{} } }.GetNewClosure()
        $badCollection = Get-AutoFlowApiCollection -Endpoint '/repos/autoflow-fiap/autoflow-infra/actions/workflows' -CollectionName 'workflows' -ApiInvoker $badTransport
        $badCollection.ErrorKind | Should Be 'INVALID_RESPONSE'

        $timeoutTransport = { param($Endpoint) [pscustomobject]@{ Success = $false; StatusCode = 0; Data = $null; ErrorKind = 'TIMEOUT'; Message = 'timeout'; Headers = @{} } }.GetNewClosure()
        $timedOut = Get-AutoFlowApiCollection -Endpoint '/repos/autoflow-fiap/autoflow-infra/actions/workflows' -CollectionName 'workflows' -ApiInvoker $timeoutTransport
        $timedOut.ErrorKind | Should Be 'TIMEOUT'
    }

    It 'reports raw run and job states, commit SHA and verified run links' {
        $transport = New-StatusApiMock
        $status = Get-AutoFlowStatus -Environment homolog -ApiInvoker $transport
        @($status.Repositories).Count | Should Be 4
        $status.HasQueryErrors | Should Be $false
        $status.Repositories[0].Branch | Should Be 'develop'
        $run = $status.Repositories[0].Workflows[0].LatestRun
        $run.Status | Should Be 'waiting'
        $run.Conclusion | Should Be $null
        $run.CommitSha | Should Be 'abcdef0123456789abcdef0123456789abcdef01'
        $run.ApprovalPending | Should Be $true
        $run.PendingDeployments[0].Environment | Should Be 'homolog'
        $run.PendingDeployments[0].ReviewerCount | Should Be 1
        (Format-AutoFlowStatusText $status) | Should Match 'Aprovacao pendente confirmada pela API'
        @($run.Jobs | Where-Object { $_.Conclusion -eq 'failure' }).Count | Should Be 1
        @($run.Jobs | Where-Object { $_.Conclusion -eq 'cancelled' }).Count | Should Be 1
        @($run.Jobs | Where-Object { $_.Conclusion -eq 'skipped' }).Count | Should Be 1
        @($run.Jobs | Where-Object { $_.Status -eq 'waiting' }).Count | Should Be 1
        $observedStatuses = @($status.Repositories | ForEach-Object { $_.Workflows | ForEach-Object { $_.LatestRun.Status } })
        foreach ($expectedStatus in @('queued', 'in_progress', 'waiting', 'completed')) {
            ($observedStatuses -contains $expectedStatus) | Should Be $true
        }
        (Format-AutoFlowStatusText $status) | Should Match 'status=waiting'
        (Format-AutoFlowStatusText $status) | Should Match 'conclusion=failure'
        $script:MockRequests | Where-Object { $_ -match '^/repos/autoflow-fiap/' } | Should Not BeNullOrEmpty

        $productionStatus = Get-AutoFlowStatus -Environment production -ApiInvoker $transport
        @($productionStatus.Repositories).Count | Should Be 4
        @($productionStatus.Repositories | Where-Object { $_.Branch -ne 'main' }).Count | Should Be 0
        @($productionStatus.Repositories | ForEach-Object { $_.Workflows } | Where-Object { $_.LatestRun -and $_.LatestRun.Branch -ne 'main' }).Count | Should Be 0
    }

    It 'queries and validates both environments without reading secret values' {
        $transport = New-ValidationApiMock
        $validation = Invoke-AutoFlowValidation -Environment homolog -ApiInvoker $transport
        @($validation.EnvironmentsChecked).Count | Should Be 2
        $script:MockRequests -join "`n" | Should Match '/environments/production/variables'
        $script:MockRequests -join "`n" | Should Match '/environments/homolog/variables'
        $script:MockRequests -join "`n" | Should Match '/environments/production/secrets'
        $script:MockRequests -join "`n" | Should Match '/environments/homolog/secrets'
        $validation.StateContract.State | Should Be 'VALID'
        @($validation.Findings | Where-Object { $_.Code -eq 'TERRAFORM_STATE_CONTRACT_INVALID' }).Count | Should Be 0
        $secretEntry = @($validation.Repositories[0].Environments[0].SecretNames | Where-Object { $_ -eq 'AWS_SESSION_TOKEN' })
        $secretEntry.Count | Should Be 1
        $validation.Repositories[0].Environments[0].PSObject.Properties['SecretValues'] | Should Be $null
    }

    It 'maps application RDS references to the producer key in homolog and production' {
        $validation = Invoke-AutoFlowValidation -Environment homolog -ApiInvoker (New-ValidationApiMock)
        $snapshots = @{}
        foreach ($repository in $validation.Repositories) {
            foreach ($snapshot in $repository.Environments) {
                $snapshots["$($repository.Name)|$($snapshot.Environment)"] = $snapshot
            }
        }
        $contractInput = Get-AutoFlowStateContractInput -Snapshots $snapshots -Findings (New-Object 'System.Collections.Generic.List[object]') -Environments @('homolog', 'production')
        $contractInput.Complete | Should Be $true
        foreach ($environment in @('homolog', 'production')) {
            $roots = $contractInput.Document.environments[$environment].roots
            $roots.rds.consumes.vpc_eks | Should Be $roots.vpc_eks.key
            $roots.lambda.consumes.vpc_eks | Should Be $roots.vpc_eks.key
            $roots.lambda.consumes.rds | Should Be $roots.rds.key
            $roots.application.consumes.rds | Should Be $roots.rds.key
            $roots.application.consumes.rds | Should Be $script:ValidationVariables["autoflow|$environment"]['AWS_RDS_STATE_KEY']
            $roots.api_gateway.consumes.vpc_eks | Should Be $roots.vpc_eks.key
            $roots.newrelic.consumes.vpc_eks | Should Be $roots.vpc_eks.key
        }
        (Invoke-AutoFlowStateContract -Document $contractInput.Document).State | Should Be 'VALID'
    }

    It 'reports an explicit false apply marker as an operational block, while rejecting malformed values' {
        $validation = Invoke-AutoFlowValidation -Environment homolog -ApiInvoker (New-ValidationApiMock -ApprovalMarker 'false')
        @($validation.Findings | Where-Object { $_.Code -eq 'APPLY_APPROVAL_DISABLED' -and $_.State -eq 'OPERATIONAL_BLOCKED' }).Count | Should Be 8
        @($validation.Findings | Where-Object { $_.Code -eq 'APPROVAL_MARKER_INVALID' }).Count | Should Be 0
        $validation.HasInconsistencies | Should Be $false
        $validation.HasUnknown | Should Be $false
        (Get-AutoFlowExitCode -Action validate -Validation $validation) | Should Be 4

        $transport = New-ValidationApiMock
        $script:ValidationVariables['autoflow|homolog']['TERRAFORM_APPLY_APPROVAL_CONFIGURED'] = 'FALSE'
        $malformed = Invoke-AutoFlowValidation -Environment homolog -ApiInvoker $transport
        @($malformed.Findings | Where-Object { $_.Code -eq 'APPROVAL_MARKER_INVALID' -and $_.State -eq 'INCONSISTENT' }).Count | Should Be 1
        $malformed.HasInconsistencies | Should Be $true
    }

    It 'does not mark Environments missing when inventory is inaccessible or hidden by a 404' {
        $transport = {
            param($Endpoint)
            if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)$') {
                $repo = $matches[1]
                return [pscustomobject]@{ Success = $true; StatusCode = 200; Data = [pscustomobject]@{ full_name = $repo }; ErrorKind = ''; Message = ''; Headers = @{} }
            }
            if ($Endpoint -match '/autoflow-db/environments\?') {
                return [pscustomobject]@{ Success = $false; StatusCode = 403; Data = $null; ErrorKind = 'ACCESS_DENIED'; Message = 'denied'; Headers = @{} }
            }
            return [pscustomobject]@{ Success = $false; StatusCode = 404; Data = $null; ErrorKind = 'NOT_FOUND_OR_NOT_VISIBLE'; Message = 'hidden resource'; Headers = @{} }
        }.GetNewClosure()
        $validation = Invoke-AutoFlowValidation -Environment homolog -ApiInvoker $transport
        @($validation.Findings | Where-Object { $_.Code -eq 'MISSING_ENVIRONMENT' }).Count | Should Be 0
        @($validation.Findings | Where-Object { $_.Code -eq 'ENVIRONMENT_UNKNOWN' -and $_.State -eq 'UNKNOWN' }).Count | Should Be 8
        @($validation.QueryErrors | Where-Object { $_.Kind -eq 'ACCESS_DENIED' }).Count | Should Be 1
    }

    It 'confirms a missing Environment only from a valid environment inventory response' {
        $resultFactory = {
            param($Data)
            [pscustomobject]@{ Success = $true; StatusCode = 200; Data = ConvertFrom-Json -InputObject (ConvertTo-Json -InputObject $Data -Depth 30); ErrorKind = ''; Message = ''; Headers = @{} }
        }.GetNewClosure()
        $transport = {
            param($Endpoint)
            if ($Endpoint -match '^/repos/(autoflow-fiap/[^/]+)$') {
                return (& $resultFactory @{ full_name = $matches[1] })
            }
            if ($Endpoint -match '/environments\?per_page=100') {
                return (& $resultFactory @{ total_count = 0; environments = @() })
            }
            throw 'Unexpected API request in missing environment fixture.'
        }.GetNewClosure()
        $validation = Invoke-AutoFlowValidation -Environment homolog -ApiInvoker $transport
        @($validation.Findings | Where-Object { $_.Code -eq 'MISSING_ENVIRONMENT' }).Count | Should Be 8
        @($validation.Findings | Where-Object { $_.Code -eq 'ENVIRONMENT_UNKNOWN' }).Count | Should Be 0
        $validation.HasQueryErrors | Should Be $false
    }

    It 'runs the existing six-root contract across homolog and production and rejects shared state keys' {
        $document = New-SyntheticStateContract
        $valid = Invoke-AutoFlowStateContract -Document $document
        $valid.State | Should Be 'VALID'
        $document.environments.production.roots.vpc_eks.key = $document.environments.homolog.roots.vpc_eks.key
        $isolated = Invoke-AutoFlowStateContract -Document $document
        $isolated.State | Should Be 'INCONSISTENT'
    }

    It 'returns stable process exit codes for success, inconsistency and query errors' {
        $cleanStatus = [pscustomobject]@{ HasQueryErrors = $false }
        $failedStatus = [pscustomobject]@{ HasQueryErrors = $true }
        $cleanValidation = [pscustomobject]@{ HasQueryErrors = $false; HasUnknown = $false; HasInconsistencies = $false; HasOperationalBlocks = $false }
        $invalidValidation = [pscustomobject]@{ HasQueryErrors = $false; HasUnknown = $false; HasInconsistencies = $true; HasOperationalBlocks = $false }
        $unknownValidation = [pscustomobject]@{ HasQueryErrors = $false; HasUnknown = $true; HasInconsistencies = $false; HasOperationalBlocks = $false }
        $blockedValidation = [pscustomobject]@{ HasQueryErrors = $false; HasUnknown = $false; HasInconsistencies = $false; HasOperationalBlocks = $true }
        (Get-AutoFlowExitCode -Action status -Status $cleanStatus) | Should Be 0
        (Get-AutoFlowExitCode -Action status -Status $failedStatus) | Should Be 3
        (Get-AutoFlowExitCode -Action validate -Validation $cleanValidation) | Should Be 0
        (Get-AutoFlowExitCode -Action validate -Validation $invalidValidation) | Should Be 1
        (Get-AutoFlowExitCode -Action validate -Validation $unknownValidation) | Should Be 3
        (Get-AutoFlowExitCode -Action validate -Validation $blockedValidation) | Should Be 4
    }

    It 'renders JSON and Markdown without variable values or a UTF-8 BOM' {
        $run = [pscustomobject]@{
            Id = 7; Url = 'https://github.com/autoflow-fiap/autoflow-infra/actions/runs/7'
            Status = 'completed'; Conclusion = 'success'; Branch = 'develop'; CommitSha = '0123456789abcdef'
            CreatedAt = '2026-10-30T12:00:00Z'; JobsState = 'OK'; ApprovalPending = $true
            PendingDeploymentsState = 'PENDING'
            PendingDeployments = @([pscustomobject]@{ Environment = 'homolog'; ReviewerCount = 2; CurrentUserCanApprove = $true })
            Jobs = @();
        }
        $status = [pscustomobject]@{
            Environment = 'homolog'; HasQueryErrors = $false; QueryErrors = @()
            Repositories = @([pscustomobject]@{
                Name = 'autoflow-infra'; FullName = 'autoflow-fiap/autoflow-infra'; Branch = 'develop'
                Workflows = @([pscustomobject]@{ Name = 'Pipeline'; QueryState = 'OK'; LatestRun = $run })
            })
        }
        $snapshot = [pscustomobject]@{
            Environment = 'homolog'; Branch = 'develop'; State = 'FOUND'; VariablesState = 'OK'; SecretsState = 'OK'
            Variables = @{ PRIVATE_TEST_MARKER = 'placeholder-secret-value-that-must-not-export'; AWS_REGION = 'us-east-1' }
            SecretNames = @('AWS_SESSION_TOKEN')
        }
        $validation = [pscustomobject]@{
            Environment = 'homolog'; EnvironmentsChecked = @('homolog', 'production'); HasQueryErrors = $false
            HasUnknown = $false; HasInconsistencies = $false; QueryErrors = @(); Findings = @()
            StateContract = [pscustomobject]@{ State = 'VALID'; Message = 'synthetic' }
            Repositories = @([pscustomobject]@{ Name = 'autoflow-infra'; FullName = 'autoflow-fiap/autoflow-infra'; Environments = @($snapshot) })
        }
        $report = New-AutoFlowConsolidatedReport -Status $status -Validation $validation
        $json = ConvertTo-Json -InputObject $report -Depth 30
        $markdown = ConvertTo-AutoFlowMarkdown -Report $report
        $json | Should Not Match 'placeholder-secret-value-that-must-not-export'
        $markdown | Should Match 'Recursos AWS provisionados: nao verificados'
        $markdown | Should Match 'Aprovacoes pendentes verificaveis'
        $markdown | Should Match 'homolog.*2.*True'

        $directory = Join-Path ([System.IO.Path]::GetTempPath()) ('autoflow-report-' + [Guid]::NewGuid().ToString('N'))
        [void](New-Item -ItemType Directory -Path $directory)
        try {
            $jsonPath = Join-Path $directory 'report.json'
            $markdownPath = Join-Path $directory 'report.md'
            Write-AutoFlowReportFiles -Report $report -JsonPath $jsonPath -MarkdownPath $markdownPath
            $bytes = [System.IO.File]::ReadAllBytes($jsonPath)
            $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
            $hasBom | Should Be $false
            $markdownContent = [System.IO.File]::ReadAllText($markdownPath, [System.Text.Encoding]::UTF8)
            $markdownContent | Should Match 'Relatorio do orquestrador'
            $overwriteRejected = $false
            try {
                Write-AutoFlowReportFiles -Report $report -JsonPath $jsonPath -MarkdownPath $markdownPath
            } catch {
                $overwriteRejected = $true
            }
            $overwriteRejected | Should Be $true
            [System.IO.File]::ReadAllText($markdownPath, [System.Text.Encoding]::UTF8) | Should Be $markdownContent
        } finally {
            Remove-Item -LiteralPath $directory -Recurse -Force
        }
    }

    It 'does not expose a supported write action through the command parameters' {
        $entry = Join-Path $script:OrchestrationPath 'Invoke-AutoFlowPipeline.ps1'
        $source = [System.IO.File]::ReadAllText($entry)
        $source | Should Match "Action -notin @\('status', 'validate', 'report'\)"
        $powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo.FileName = $powerShell
        $process.StartInfo.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -Environment homolog -Action apply' -f $entry
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        try {
            [void]$process.Start()
            $process.WaitForExit(30000) | Should Be $true
            $process.ExitCode | Should Be 2
        } finally {
            $process.Dispose()
        }
        $invalidEnvironment = New-Object System.Diagnostics.Process
        $invalidEnvironment.StartInfo.FileName = $powerShell
        $invalidEnvironment.StartInfo.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -Environment other -Action status' -f $entry
        $invalidEnvironment.StartInfo.UseShellExecute = $false
        $invalidEnvironment.StartInfo.CreateNoWindow = $true
        try {
            [void]$invalidEnvironment.Start()
            $invalidEnvironment.WaitForExit(30000) | Should Be $true
            $invalidEnvironment.ExitCode | Should Be 2
        } finally {
            $invalidEnvironment.Dispose()
        }
        $moduleFiles = @(Get-ChildItem -LiteralPath $script:OrchestrationPath -Filter '*.psm1' -File)
        foreach ($moduleFile in $moduleFiles) {
            $moduleSource = [System.IO.File]::ReadAllText($moduleFile.FullName)
            $moduleSource | Should Not Match '(?i)gh\s+(workflow\s+run|secret\s+set|variable\s+set)'
            $moduleSource | Should Not Match '(?i)terraform\s+(apply|destroy)'
            $moduleSource | Should Not Match '(?i)aws\s+\S+\s+(create|put|delete|update|modify)'
        }
        (Get-Content -LiteralPath (Join-Path $script:OrchestrationPath 'AutoFlow.GitHub.psm1') -Raw) | Should Match '--method GET'
    }
}
