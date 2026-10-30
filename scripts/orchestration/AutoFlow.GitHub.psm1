Set-StrictMode -Version 2.0

function New-AutoFlowApiResult {
    param(
        [bool]$Success,
        [int]$StatusCode = 0,
        $Data = $null,
        [string]$ErrorKind = '',
        [string]$Message = '',
        [hashtable]$Headers = @{}
    )
    return [pscustomobject]@{
        Success = $Success
        StatusCode = $StatusCode
        Data = $Data
        ErrorKind = $ErrorKind
        Message = $Message
        Headers = $Headers
    }
}

function ConvertFrom-AutoFlowGhResponse {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int]$ExitCode,
        [string]$StandardOutput = '',
        [string]$StandardError = ''
    )

    $statusCode = 0
    $headers = @{}
    $body = $StandardOutput
    $separator = [regex]::Match($StandardOutput, "\r?\n\r?\n")
    if ($separator.Success) {
        $headerBlock = $StandardOutput.Substring(0, $separator.Index)
        $body = $StandardOutput.Substring($separator.Index + $separator.Length)
        foreach ($line in ($headerBlock -split "\r?\n")) {
            if ($line -match '^HTTP/\S+\s+(\d{3})') {
                $statusCode = [int]$matches[1]
            } elseif ($line -match '^([^:]+):\s*(.*)$') {
                $headers[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
    }

    if ($ExitCode -ne 0 -or $statusCode -lt 200 -or $statusCode -ge 300) {
        $kind = 'API_UNAVAILABLE'
        if ($statusCode -eq 403) {
            $kind = 'ACCESS_DENIED'
            if (($headers['x-ratelimit-remaining'] -eq '0') -or ($StandardError -match '(?i)rate limit') -or ($body -match '(?i)rate limit')) {
                $kind = 'RATE_LIMIT'
            }
        } elseif ($statusCode -eq 404) {
            $kind = 'NOT_FOUND_OR_NOT_VISIBLE'
        } elseif ($statusCode -eq 429) {
            $kind = 'RATE_LIMIT'
        } elseif ($statusCode -eq 401) {
            $kind = 'ACCESS_DENIED'
        } elseif ($statusCode -ge 500 -or $statusCode -eq 0) {
            $kind = 'API_UNAVAILABLE'
        }
        return (New-AutoFlowApiResult -Success $false -StatusCode $statusCode -ErrorKind $kind -Message 'A consulta GitHub falhou; detalhes de resposta foram omitidos.' -Headers $headers)
    }

    try {
        if ($body.TrimStart().StartsWith('[')) {
            if ($body.Trim() -match '^\[\s*\]$') {
                $data = New-Object object[] 0
            } else {
                $data = ConvertFrom-Json -InputObject $body -ErrorAction Stop
            }
        } else {
            $data = ConvertFrom-Json -InputObject $body -ErrorAction Stop
        }
    } catch {
        return (New-AutoFlowApiResult -Success $false -StatusCode $statusCode -ErrorKind 'INVALID_RESPONSE' -Message 'A API retornou JSON invalido.' -Headers $headers)
    }
    return (New-AutoFlowApiResult -Success $true -StatusCode $statusCode -Data $data -Headers $headers)
}

function Invoke-AutoFlowGitHubApi {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Endpoint)

    if ($Endpoint -notmatch '^/repos/autoflow-fiap/(autoflow-infra|autoflow-db|autoflow-lambda|autoflow)(/|\?|$)' -or
        $Endpoint -notmatch '^/repos/autoflow-fiap/(autoflow-infra|autoflow-db|autoflow-lambda|autoflow)[A-Za-z0-9/_?=&.-]*$') {
        return (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_ENDPOINT' -Message 'Endpoint fora da allowlist.')
    }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        return (New-AutoFlowApiResult -Success $false -ErrorKind 'CLI_UNAVAILABLE' -Message 'GitHub CLI (gh) nao encontrado.')
    }

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = (Get-Command gh -ErrorAction Stop).Source
    $startInfo.Arguments = 'api --include --method GET --hostname github.com "{0}"' -f $Endpoint.TrimStart('/')
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
            return (New-AutoFlowApiResult -Success $false -ErrorKind 'CLI_UNAVAILABLE' -Message 'Nao foi possivel iniciar gh.')
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            try { $process.Kill() } catch { }
            return (New-AutoFlowApiResult -Success $false -ErrorKind 'TIMEOUT' -Message 'Consulta GitHub excedeu 30 segundos.')
        }
        $process.WaitForExit()
        return (ConvertFrom-AutoFlowGhResponse -ExitCode $process.ExitCode -StandardOutput $stdoutTask.Result -StandardError $stderrTask.Result)
    } catch {
        return (New-AutoFlowApiResult -Success $false -ErrorKind 'API_UNAVAILABLE' -Message 'Falha local ao executar a consulta GitHub.')
    } finally {
        $process.Dispose()
    }
}

function Add-AutoFlowPageQuery {
    param([string]$Endpoint, [int]$Page, [int]$PerPage = 100)
    if ($Endpoint -match '([?&])page=') {
        return [regex]::Replace($Endpoint, '([?&])page=\d+', ('$1page=' + $Page))
    }
    if ($Endpoint -match '\?') {
        if ($Endpoint -match '([?&])per_page=') { return "${Endpoint}&page=$Page" }
        return "${Endpoint}&per_page=$PerPage&page=$Page"
    }
    return "${Endpoint}?per_page=$PerPage&page=$Page"
}

function Get-AutoFlowApiCollection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$CollectionName,
        [switch]$FirstPageOnly,
        [ValidateRange(1, 100)][int]$PerPage = 100,
        [scriptblock]$ApiInvoker = ${function:Invoke-AutoFlowGitHubApi}
    )

    $allItems = New-Object System.Collections.Generic.List[object]
    $page = 1
    $expectedTotal = $null
    do {
        $pageEndpoint = Add-AutoFlowPageQuery -Endpoint $Endpoint -Page $page -PerPage $PerPage
        $response = & $ApiInvoker $pageEndpoint
        if (-not $response -or -not $response.Success) {
            if ($response) { return $response }
            return (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Resposta vazia do transporte GitHub.')
        }
        if (-not $response.Data -or $null -eq $response.Data.PSObject.Properties[$CollectionName] -or $null -eq $response.Data.PSObject.Properties['total_count']) {
            return (New-AutoFlowApiResult -Success $false -StatusCode $response.StatusCode -ErrorKind 'INVALID_RESPONSE' -Message "A resposta nao contem a colecao $CollectionName.")
        }
        $collectionValue = $response.Data.PSObject.Properties[$CollectionName].Value
        if ($collectionValue -isnot [System.Array]) {
            return (New-AutoFlowApiResult -Success $false -StatusCode $response.StatusCode -ErrorKind 'INVALID_RESPONSE' -Message "A colecao $CollectionName nao e um array.")
        }
        $items = @($collectionValue)
        foreach ($item in $items) { [void]$allItems.Add($item) }
        if ($null -eq $expectedTotal) {
            $total = 0L
            if (-not [long]::TryParse([string]$response.Data.total_count, [ref]$total) -or $total -lt 0 -or (-not $FirstPageOnly -and $total -gt 10000)) {
                return (New-AutoFlowApiResult -Success $false -StatusCode $response.StatusCode -ErrorKind 'INVALID_RESPONSE' -Message 'total_count invalido na resposta GitHub.')
            }
            $expectedTotal = $total
        }
        if ($allItems.Count -gt $expectedTotal -or $allItems.Count -gt 10000) {
            return (New-AutoFlowApiResult -Success $false -StatusCode $response.StatusCode -ErrorKind 'INVALID_RESPONSE' -Message 'Contagem da colecao GitHub invalida.')
        }
        $page++
    } while (-not $FirstPageOnly -and $allItems.Count -lt $expectedTotal -and $allItems.Count -gt 0)

    if (-not $FirstPageOnly -and $allItems.Count -lt $expectedTotal) {
        return (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'A resposta GitHub foi truncada.')
    }
    return (New-AutoFlowApiResult -Success $true -StatusCode 200 -Data @($allItems.ToArray()))
}

function Test-AutoFlowObjectProperty {
    param($Object, [string]$Name)
    return ($null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name])
}

function Get-AutoFlowStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidateSet('homolog', 'production')][string]$Environment,
        [scriptblock]$ApiInvoker = ${function:Invoke-AutoFlowGitHubApi}
    )

    Import-Module (Join-Path $PSScriptRoot 'AutoFlow.Config.psm1')
    $repositories = @(Get-AutoFlowRepositories)
    $results = New-Object System.Collections.Generic.List[object]
    $queryErrors = New-Object System.Collections.Generic.List[object]

    foreach ($repository in $repositories) {
        $branch = $repository.Branches[$Environment]
        $repoResult = [ordered]@{
            Name = $repository.Name
            FullName = $repository.FullName
            Environment = $Environment
            Branch = $branch
            RepositoryState = 'UNKNOWN'
            BranchState = 'UNKNOWN'
            WorkflowQueryState = 'UNKNOWN'
            Workflows = @()
        }
        $repoResponse = & $ApiInvoker "/repos/$($repository.FullName)"
        if (-not $repoResponse.Success) {
            $repoResult.RepositoryState = $repoResponse.ErrorKind
            [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName 'repository' $repoResponse))
            [void]$results.Add([pscustomobject]$repoResult)
            continue
        }
        if (-not (Test-AutoFlowObjectProperty $repoResponse.Data 'full_name') -or $repoResponse.Data.full_name -ine $repository.FullName) {
            $repoResult.RepositoryState = 'INVALID_RESPONSE'
            [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName 'repository' (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Repositorio inesperado.')))
            [void]$results.Add([pscustomobject]$repoResult)
            continue
        }
        $repoResult.RepositoryState = 'FOUND'

        $branchResponse = & $ApiInvoker "/repos/$($repository.FullName)/branches/$branch"
        if (-not $branchResponse.Success) {
            $repoResult.BranchState = $branchResponse.ErrorKind
            [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName 'branch' $branchResponse))
        } elseif ((Test-AutoFlowObjectProperty $branchResponse.Data 'name') -and $branchResponse.Data.name -is [string] -and $branchResponse.Data.name -ceq $branch -and (Test-AutoFlowObjectProperty $branchResponse.Data 'protected') -and $branchResponse.Data.protected -is [bool]) {
            $repoResult.BranchState = 'FOUND'
        } else {
            $repoResult.BranchState = 'INVALID_RESPONSE'
            [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName 'branch' (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Branch retornada invalida.')))
        }

        $workflowResponse = Get-AutoFlowApiCollection -Endpoint "/repos/$($repository.FullName)/actions/workflows" -CollectionName 'workflows' -ApiInvoker $ApiInvoker
        if (-not $workflowResponse.Success) {
            $repoResult.WorkflowQueryState = $workflowResponse.ErrorKind
            [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName 'workflows' $workflowResponse))
            [void]$results.Add([pscustomobject]$repoResult)
            continue
        }
        $repoResult.WorkflowQueryState = 'OK'
        $workflowStatuses = New-Object System.Collections.Generic.List[object]
        foreach ($workflow in @($workflowResponse.Data)) {
            $workflowId = 0L
            if (-not (Test-AutoFlowObjectProperty $workflow 'id') -or -not [long]::TryParse([string]$workflow.id, [ref]$workflowId) -or $workflowId -le 0 -or -not (Test-AutoFlowObjectProperty $workflow 'name') -or $workflow.name -isnot [string] -or -not (Test-AutoFlowObjectProperty $workflow 'state') -or $workflow.state -isnot [string]) {
                [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName 'workflows' (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Workflow sem campos obrigatorios.')))
                continue
            }
            $workflowRecord = [ordered]@{
                Id = $workflowId
                Name = [string]$workflow.name
                State = [string]$workflow.state
                QueryState = 'UNKNOWN'
                LatestRun = $null
            }
            $runEndpoint = "/repos/$($repository.FullName)/actions/workflows/$workflowId/runs?branch=$branch&per_page=1"
            $runResponse = Get-AutoFlowApiCollection -Endpoint $runEndpoint -CollectionName 'workflow_runs' -FirstPageOnly -ApiInvoker $ApiInvoker
            if (-not $runResponse.Success) {
                $workflowRecord.QueryState = $runResponse.ErrorKind
                [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "runs:$($workflow.name)" $runResponse))
                [void]$workflowStatuses.Add([pscustomobject]$workflowRecord)
                continue
            }
            if (@($runResponse.Data).Count -eq 0) {
                $workflowRecord.QueryState = 'NO_RUNS'
                [void]$workflowStatuses.Add([pscustomobject]$workflowRecord)
                continue
            }
            $run = @($runResponse.Data)[0]
            $runId = 0L
            if (-not (Test-AutoFlowObjectProperty $run 'id') -or -not [long]::TryParse([string]$run.id, [ref]$runId) -or $runId -le 0 -or -not (Test-AutoFlowObjectProperty $run 'status') -or $run.status -isnot [string] -or -not (Test-AutoFlowObjectProperty $run 'head_branch') -or $run.head_branch -isnot [string] -or -not (Test-AutoFlowObjectProperty $run 'head_sha') -or $run.head_sha -isnot [string] -or $run.head_sha -notmatch '^(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$' -or -not (Test-AutoFlowObjectProperty $run 'html_url') -or $run.html_url -isnot [string] -or -not (Test-AutoFlowGitHubUrl $run.html_url $repository.FullName)) {
                $workflowRecord.QueryState = 'INVALID_RESPONSE'
                [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "runs:$($workflow.name)" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Run sem campos obrigatorios.')))
                [void]$workflowStatuses.Add([pscustomobject]$workflowRecord)
                continue
            }
            if ($run.head_branch -cne $branch) {
                $workflowRecord.QueryState = 'INVALID_RESPONSE'
                [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "runs:$($workflow.name)" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Run em branch diferente da selecionada.')))
                [void]$workflowStatuses.Add([pscustomobject]$workflowRecord)
                continue
            }
            $jobsResponse = Get-AutoFlowApiCollection -Endpoint "/repos/$($repository.FullName)/actions/runs/$runId/jobs" -CollectionName 'jobs' -ApiInvoker $ApiInvoker
            $jobs = @()
            $jobsState = 'OK'
            if (-not $jobsResponse.Success) {
                $jobsState = $jobsResponse.ErrorKind
                [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "jobs:$($run.id)" $jobsResponse))
            } else {
                foreach ($job in @($jobsResponse.Data)) {
                    $jobId = 0L
                    if (-not (Test-AutoFlowObjectProperty $job 'id') -or -not [long]::TryParse([string]$job.id, [ref]$jobId) -or $jobId -le 0 -or -not (Test-AutoFlowObjectProperty $job 'name') -or $job.name -isnot [string] -or -not (Test-AutoFlowObjectProperty $job 'status') -or $job.status -isnot [string] -or -not (Test-AutoFlowObjectProperty $job 'html_url') -or $job.html_url -isnot [string] -or -not (Test-AutoFlowGitHubUrl $job.html_url $repository.FullName)) {
                        $jobsState = 'INVALID_RESPONSE'
                        [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "jobs:$($run.id)" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Job sem campos obrigatorios.')))
                        continue
                    }
                    $jobs += [pscustomobject]@{
                        Id = $jobId
                        Name = [string]$job.name
                        Status = [string]$job.status
                        Conclusion = if (Test-AutoFlowObjectProperty $job 'conclusion') { $job.conclusion } else { $null }
                        Url = [string]$job.html_url
                        ApprovalPending = ([string]$job.status -eq 'waiting')
                    }
                }
            }
            $pendingDeploymentState = 'NOT_WAITING'
            $pendingDeployments = @()
            $waitingJobCount = @($jobs | Where-Object { $_.Status -eq 'waiting' }).Count
            if ([string]$run.status -eq 'waiting' -or $waitingJobCount -gt 0) {
                $pendingResponse = & $ApiInvoker "/repos/$($repository.FullName)/actions/runs/$runId/pending_deployments"
                if (-not $pendingResponse.Success) {
                    $pendingDeploymentState = $pendingResponse.ErrorKind
                    [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "pending_deployments:$runId" $pendingResponse))
                } elseif ($pendingResponse.Data -isnot [System.Array]) {
                    $pendingDeploymentState = 'INVALID_RESPONSE'
                    [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "pending_deployments:$runId" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Pending deployments nao e um array.')))
                } else {
                    $validPendingDeployments = $true
                    foreach ($pendingDeployment in @($pendingResponse.Data)) {
                        if (-not (Test-AutoFlowObjectProperty $pendingDeployment 'environment') -or -not (Test-AutoFlowObjectProperty $pendingDeployment.environment 'name') -or $pendingDeployment.environment.name -isnot [string] -or -not (Test-AutoFlowObjectProperty $pendingDeployment 'reviewers') -or $pendingDeployment.reviewers -isnot [System.Array] -or -not (Test-AutoFlowObjectProperty $pendingDeployment 'current_user_can_approve') -or $pendingDeployment.current_user_can_approve -isnot [bool]) {
                            $validPendingDeployments = $false
                            break
                        }
                        $pendingDeployments += [pscustomobject]@{
                            Environment = [string]$pendingDeployment.environment.name
                            ReviewerCount = @($pendingDeployment.reviewers).Count
                            CurrentUserCanApprove = [bool]$pendingDeployment.current_user_can_approve
                        }
                    }
                    if (-not $validPendingDeployments) {
                        $pendingDeploymentState = 'INVALID_RESPONSE'
                        [void]$queryErrors.Add((New-AutoFlowQueryError $repository.FullName "pending_deployments:$runId" (New-AutoFlowApiResult -Success $false -ErrorKind 'INVALID_RESPONSE' -Message 'Pending deployment sem campos obrigatorios.')))
                    } elseif ($pendingDeployments.Count -gt 0) {
                        $pendingDeploymentState = 'PENDING'
                    } else {
                        $pendingDeploymentState = 'NONE'
                    }
                }
            }
            $workflowRecord.QueryState = 'OK'
            $workflowRecord.LatestRun = [pscustomobject]@{
                Id = $runId
                Url = [string]$run.html_url
                Status = [string]$run.status
                Conclusion = if (Test-AutoFlowObjectProperty $run 'conclusion') { $run.conclusion } else { $null }
                Branch = [string]$run.head_branch
                CommitSha = [string]$run.head_sha
                CreatedAt = if (Test-AutoFlowObjectProperty $run 'created_at') { $run.created_at } else { $null }
                JobsState = $jobsState
                Jobs = @($jobs)
                ApprovalPending = ($pendingDeploymentState -eq 'PENDING')
                PendingDeploymentsState = $pendingDeploymentState
                PendingDeployments = @($pendingDeployments)
            }
            [void]$workflowStatuses.Add([pscustomobject]$workflowRecord)
        }
        $repoResult.Workflows = @($workflowStatuses.ToArray())
        [void]$results.Add([pscustomobject]$repoResult)
    }

    return [pscustomobject]@{
        Environment = $Environment
        Repositories = @($results.ToArray())
        QueryErrors = @($queryErrors.ToArray())
        HasQueryErrors = ($queryErrors.Count -gt 0)
    }
}

function New-AutoFlowQueryError {
    param([string]$Repository, [string]$Resource, $Response)
    return [pscustomobject]@{
        Repository = $Repository
        Resource = $Resource
        Status = if ($Response.StatusCode -gt 0) { [string]$Response.StatusCode } else { [string]$Response.ErrorKind }
        Kind = [string]$Response.ErrorKind
        Message = [string]$Response.Message
    }
}

function Test-AutoFlowGitHubUrl {
    param([string]$Url, [string]$FullName)
    $uri = $null
    if (-not [System.Uri]::TryCreate($Url, [System.UriKind]::Absolute, [ref]$uri)) { return $false }
    return ($uri.Scheme -eq 'https' -and $uri.Host -eq 'github.com' -and $uri.AbsolutePath.StartsWith("/$FullName/", [StringComparison]::OrdinalIgnoreCase))
}

Export-ModuleMember -Function Invoke-AutoFlowGitHubApi, Get-AutoFlowApiCollection, Get-AutoFlowStatus, New-AutoFlowApiResult, ConvertFrom-AutoFlowGhResponse, Test-AutoFlowGitHubUrl
