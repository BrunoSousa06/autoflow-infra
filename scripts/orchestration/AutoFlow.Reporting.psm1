Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'AutoFlow.Config.psm1')

function Format-AutoFlowOptionalValue {
    param($Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return 'not_reported' }
    return [string]$Value
}

function Format-AutoFlowStatusText {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Status)

    $lines = New-Object System.Collections.Generic.List[string]
    [void]$lines.Add("Status das pipelines - ambiente $($Status.Environment)")
    foreach ($repository in @($Status.Repositories)) {
        [void]$lines.Add('')
        [void]$lines.Add("$($repository.FullName) | branch=$($repository.Branch) | repo=$($repository.RepositoryState) | branch_state=$($repository.BranchState)")
        if ($repository.WorkflowQueryState -ne 'OK') {
            [void]$lines.Add("  workflows: $($repository.WorkflowQueryState)")
            continue
        }
        foreach ($workflow in @($repository.Workflows)) {
            if ($workflow.QueryState -eq 'NO_RUNS') {
                [void]$lines.Add("  $($workflow.Name) | sem execucoes retornadas pela API")
                continue
            }
            if ($workflow.QueryState -ne 'OK' -or $null -eq $workflow.LatestRun) {
                [void]$lines.Add("  $($workflow.Name) | consulta=$($workflow.QueryState)")
                continue
            }
            $run = $workflow.LatestRun
            $conclusion = Format-AutoFlowOptionalValue $run.Conclusion
            [void]$lines.Add("  $($workflow.Name) | run=$($run.Id) | status=$($run.Status) | conclusion=$conclusion | branch=$($run.Branch) | commit=$($run.CommitSha)")
            [void]$lines.Add("    URL: $($run.Url)")
            if ($run.ApprovalPending) {
                foreach ($pending in @($run.PendingDeployments)) {
                    [void]$lines.Add("    Aprovacao pendente confirmada pela API: environment=$($pending.Environment) | reviewers=$($pending.ReviewerCount) | current_user_can_approve=$($pending.CurrentUserCanApprove)")
                }
            } elseif ($run.Status -eq 'waiting') {
                [void]$lines.Add("    Status waiting; pending_deployments=$($run.PendingDeploymentsState); motivo nao inferido.")
            }
            if ($run.JobsState -ne 'OK') {
                [void]$lines.Add("    jobs: $($run.JobsState)")
            } else {
                foreach ($job in @($run.Jobs)) {
                    if ($job.Status -eq 'waiting' -or $job.Conclusion -in @('failure', 'cancelled', 'skipped')) {
                        $jobConclusion = Format-AutoFlowOptionalValue $job.Conclusion
                        [void]$lines.Add("    job=$($job.Name) | status=$($job.Status) | conclusion=$jobConclusion | url=$($job.Url)")
                    }
                }
            }
        }
    }
    foreach ($errorRecord in @($Status.QueryErrors)) {
        [void]$lines.Add("Consulta indisponivel: $($errorRecord.Repository) / $($errorRecord.Resource) / $($errorRecord.Kind) / $($errorRecord.Status)")
    }
    return ($lines -join [Environment]::NewLine)
}

function Format-AutoFlowValidationText {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Validation)

    $lines = New-Object System.Collections.Generic.List[string]
    [void]$lines.Add('Validacao somente leitura dos Environments homolog e production')
    [void]$lines.Add("Contrato dos seis Terraform roots: $($Validation.StateContract.State) - $($Validation.StateContract.Message)")
    if (@($Validation.Findings).Count -eq 0) {
        [void]$lines.Add('Nenhuma inconsistencia ou informacao desconhecida foi encontrada.')
    } else {
        foreach ($finding in @($Validation.Findings)) {
            $environmentLabel = if ($finding.Environment) { $finding.Environment } else { 'ambos' }
            [void]$lines.Add("[$($finding.State)] $($finding.Repository) / $environmentLabel / $($finding.Code): $($finding.Message)")
        }
    }
    foreach ($errorRecord in @($Validation.QueryErrors)) {
        [void]$lines.Add("Consulta indisponivel: $($errorRecord.Repository) / $($errorRecord.Resource) / $($errorRecord.Kind) / HTTP $($errorRecord.StatusCode)")
    }
    return ($lines -join [Environment]::NewLine)
}

function Get-AutoFlowRepositoryRun {
    param($Status, [string]$Repository, [string]$WorkflowName)
    $repoEntry = @($Status.Repositories | Where-Object { $_.Name -eq $Repository }) | Select-Object -First 1
    if (-not $repoEntry) { return $null }
    $workflowEntry = @($repoEntry.Workflows | Where-Object { $_.Name -eq $WorkflowName -and $_.QueryState -eq 'OK' -and $null -ne $_.LatestRun }) | Select-Object -First 1
    if (-not $workflowEntry) { return $null }
    return $workflowEntry.LatestRun
}

function New-AutoFlowDependencyStatus {
    param($Status)

    $dependencies = @(
        @{ Consumer = 'autoflow-db'; Needs = 'autoflow-infra / Pipeline (VPC/EKS)'; Upstream = 'autoflow-infra'; Workflow = 'Pipeline' },
        @{ Consumer = 'autoflow-lambda'; Needs = 'autoflow-infra / Pipeline (VPC/EKS)'; Upstream = 'autoflow-infra'; Workflow = 'Pipeline' },
        @{ Consumer = 'autoflow-lambda'; Needs = 'autoflow-db / RDS Pipeline'; Upstream = 'autoflow-db'; Workflow = 'RDS Pipeline' },
        @{ Consumer = 'autoflow'; Needs = 'autoflow-db / RDS Pipeline'; Upstream = 'autoflow-db'; Workflow = 'RDS Pipeline' },
        @{ Consumer = 'autoflow-infra'; Needs = 'VPC/EKS antes de API Gateway e New Relic'; Upstream = 'autoflow-infra'; Workflow = 'Pipeline' }
    )
    $result = New-Object System.Collections.Generic.List[object]
    foreach ($dependency in $dependencies) {
        $run = Get-AutoFlowRepositoryRun $Status $dependency.Upstream $dependency.Workflow
        $state = 'NOT_VERIFIED'
        $runId = $null
        if ($run) {
            $runId = $run.Id
            if ($run.Status -eq 'waiting') { $state = 'WAITING' }
            elseif ($run.Status -in @('queued', 'in_progress')) { $state = [string]$run.Status }
            elseif ($run.Status -eq 'completed' -and $run.Conclusion -eq 'success') { $state = 'WORKFLOW_SUCCESS_RESOURCE_UNVERIFIED' }
            elseif ($run.Status -eq 'completed' -and $run.Conclusion -in @('failure', 'cancelled', 'skipped')) { $state = 'POTENTIAL_BLOCKER' }
            elseif ($run.Status -eq 'completed') { $state = 'COMPLETED_RESULT_UNAVAILABLE' }
            else { $state = 'UNKNOWN' }
        }
        [void]$result.Add([pscustomobject]@{
            Consumer = $dependency.Consumer
            Dependency = $dependency.Needs
            State = $state
            UpstreamRunId = $runId
        })
    }
    return @($result.ToArray())
}

function New-AutoFlowRecommendations {
    param($Validation, $Status, $Dependencies)

    $recommendations = New-Object System.Collections.Generic.List[string]
    foreach ($finding in @($Validation.Findings)) {
        if ($finding.State -eq 'INCONSISTENT') {
            switch -Regex ($finding.Code) {
                'APPROVAL|REVIEWERS|BRANCH_POLICY' { [void]$recommendations.Add("Revisar manualmente a protecao e a branch policy de $($finding.Repository)/$($finding.Environment) no GitHub; manter o gate nativo."); break }
                'STATE|KEY|AWS_ACCOUNT|AWS_REGION|BUCKET' { [void]$recommendations.Add("Confrontar as Variables de State/AWS de $($finding.Repository)/$($finding.Environment) com os roots produtores e consumidores antes de qualquer deploy."); break }
                'SECRET' { [void]$recommendations.Add("Cadastrar ou revisar manualmente apenas o nome de Secret exigido em $($finding.Repository)/$($finding.Environment); a ferramenta nao le seu valor."); break }
                default { [void]$recommendations.Add("Revisar manualmente $($finding.Code) em $($finding.Repository)/$($finding.Environment), consultando a configuracao no GitHub.") }
            }
        } elseif ($finding.State -eq 'UNKNOWN') {
            [void]$recommendations.Add("Conceder somente as permissoes GitHub de leitura necessarias ou repetir a consulta de $($finding.Repository)/$($finding.Environment); UNKNOWN nao significa ausente.")
        }
    }
    foreach ($dependency in @($Dependencies | Where-Object { $_.State -eq 'POTENTIAL_BLOCKER' -or $_.State -eq 'WAITING' })) {
        [void]$recommendations.Add("Inspecionar manualmente a execucao upstream $($dependency.UpstreamRunId) de $($dependency.Dependency); o resultado da pipeline nao comprova estado de recursos AWS.")
    }
    foreach ($repository in @($Status.Repositories)) {
        foreach ($workflow in @($repository.Workflows)) {
            if ($workflow.LatestRun -and $workflow.LatestRun.ApprovalPending) {
                foreach ($pending in @($workflow.LatestRun.PendingDeployments)) {
                    [void]$recommendations.Add("Verificar manualmente o Environment $($pending.Environment) da execucao $($workflow.LatestRun.Id); nenhuma aprovacao foi enviada pelo orquestrador.")
                }
            }
            if ($workflow.LatestRun -and $workflow.LatestRun.Conclusion -in @('failure', 'cancelled', 'skipped')) {
                [void]$recommendations.Add("Inspecionar os logs da execucao $($workflow.LatestRun.Id) de $($repository.FullName)/$($workflow.Name) no GitHub Actions.")
            }
        }
    }
    if ($recommendations.Count -eq 0) {
        [void]$recommendations.Add('Nenhuma acao manual foi derivada dos dados consultados; confirme separadamente as dependencias operacionais antes de promover mudancas.')
    }
    return @($recommendations.ToArray() | Select-Object -Unique)
}

function New-AutoFlowConsolidatedReport {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Status,
        [Parameter(Mandatory = $true)]$Validation
    )

    $dependencies = @(New-AutoFlowDependencyStatus $Status)
    $safeRepositories = New-Object System.Collections.Generic.List[object]
    foreach ($repository in @($Validation.Repositories)) {
        $safeEnvironments = New-Object System.Collections.Generic.List[object]
        foreach ($snapshot in @($repository.Environments)) {
            [void]$safeEnvironments.Add([pscustomobject]@{
                Name = $snapshot.Environment
                Branch = $snapshot.Branch
                EnvironmentState = $snapshot.State
                VariablesState = $snapshot.VariablesState
                SecretNamesState = $snapshot.SecretsState
                VariableNames = @($snapshot.Variables.Keys | Sort-Object)
                SecretNames = @($snapshot.SecretNames | Sort-Object)
            })
        }
        [void]$safeRepositories.Add([pscustomobject]@{
            Name = $repository.Name
            FullName = $repository.FullName
            Environments = @($safeEnvironments.ToArray())
        })
    }
    $report = [pscustomobject]@{
        GeneratedAtUtc = [DateTime]::UtcNow.ToString('o')
        SelectedEnvironment = $Status.Environment
        ReadOnly = $true
        Repositories = @($safeRepositories.ToArray())
        PipelineStatus = $Status
        Validation = [pscustomobject]@{
            EnvironmentsChecked = @($Validation.EnvironmentsChecked)
            StateContract = $Validation.StateContract
            Findings = @($Validation.Findings)
            QueryErrors = @($Validation.QueryErrors)
        }
        Dependencies = @($dependencies)
        Recommendations = @(New-AutoFlowRecommendations $Validation $Status $dependencies)
        ResourceProvisioningClaimed = $false
    }
    return $report
}

function ConvertTo-AutoFlowMarkdown {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Report)

    $lines = New-Object System.Collections.Generic.List[string]
    [void]$lines.Add('# Relatorio do orquestrador de pipelines AutoFlow')
    [void]$lines.Add('')
    [void]$lines.Add("- Gerado em UTC: $($Report.GeneratedAtUtc)")
    [void]$lines.Add("- Ambiente selecionado para status: $($Report.SelectedEnvironment)")
    [void]$lines.Add('- Modo: somente leitura')
    [void]$lines.Add('- Recursos AWS provisionados: nao verificados por este relatorio')
    [void]$lines.Add('')
    [void]$lines.Add('## Repositorios e ambientes')
    [void]$lines.Add('')
    [void]$lines.Add('| Repositorio | Environment | Branch | Environment | Variables | Secret names |')
    [void]$lines.Add('|---|---|---|---|---|---|')
    foreach ($repository in @($Report.Repositories)) {
        foreach ($environment in @($repository.Environments)) {
            [void]$lines.Add("| $($repository.FullName) | $($environment.Name) | $($environment.Branch) | $($environment.EnvironmentState) | $($environment.VariablesState) | $($environment.SecretNamesState) |")
        }
    }
    [void]$lines.Add('')
    [void]$lines.Add('## Workflows e ultimos resultados')
    [void]$lines.Add('')
    [void]$lines.Add('| Repositorio | Branch | Workflow | Run | Status | Conclusion | Commit | URL |')
    [void]$lines.Add('|---|---|---|---:|---|---|---|---|')
    $pendingApprovalRows = New-Object System.Collections.Generic.List[string]
    foreach ($repository in @($Report.PipelineStatus.Repositories)) {
        foreach ($workflow in @($repository.Workflows)) {
            if ($workflow.LatestRun) {
                $run = $workflow.LatestRun
                $conclusion = Format-AutoFlowOptionalValue $run.Conclusion
                [void]$lines.Add("| $($repository.FullName) | $($repository.Branch) | $($workflow.Name) | $($run.Id) | $($run.Status) | $conclusion | $($run.CommitSha) | $($run.Url) |")
                foreach ($job in @($run.Jobs | Where-Object { $_.Status -eq 'waiting' -or $_.Conclusion -in @('failure', 'cancelled', 'skipped') })) {
                    $jobConclusion = Format-AutoFlowOptionalValue $job.Conclusion
                    [void]$lines.Add("|  |  | Job: $($job.Name) | $($job.Id) | $($job.Status) | $jobConclusion |  | $($job.Url) |")
                }
                if ($run.ApprovalPending) {
                    foreach ($pending in @($run.PendingDeployments)) {
                        [void]$pendingApprovalRows.Add("| $($repository.FullName) | $($workflow.Name) | $($run.Id) | $($pending.Environment) | $($pending.ReviewerCount) | $($pending.CurrentUserCanApprove) | $($run.Url) |")
                    }
                }
            } else {
                [void]$lines.Add("| $($repository.FullName) | $($repository.Branch) | $($workflow.Name) |  | $($workflow.QueryState) | not_reported |  |  |")
            }
        }
    }
    [void]$lines.Add('')
    [void]$lines.Add('## Aprovacoes pendentes verificaveis')
    [void]$lines.Add('')
    [void]$lines.Add('| Repositorio | Workflow | Run | Environment | Reviewers | Usuario atual pode aprovar | URL |')
    [void]$lines.Add('|---|---|---:|---|---:|---|---|')
    if ($pendingApprovalRows.Count -gt 0) {
        foreach ($row in $pendingApprovalRows) { [void]$lines.Add($row) }
    } else {
        [void]$lines.Add('Nenhuma resposta consultada confirmou uma aprovacao pendente; estados `waiting` sem dados de pending deployments nao foram inferidos como aprovacao.')
    }
    foreach ($errorRecord in @($Report.PipelineStatus.QueryErrors)) {
        [void]$lines.Add("- [QUERY_ERROR] $($errorRecord.Repository)/$($errorRecord.Resource): $($errorRecord.Kind) ($($errorRecord.Status))")
    }
    [void]$lines.Add('')
    [void]$lines.Add('## Validacao e problemas de configuracao')
    [void]$lines.Add('')
    [void]$lines.Add("- Contrato dos seis States: $($Report.Validation.StateContract.State) - $($Report.Validation.StateContract.Message)")
    foreach ($finding in @($Report.Validation.Findings)) {
        $environmentLabel = if ($finding.Environment) { $finding.Environment } else { 'ambos' }
        [void]$lines.Add("- [$($finding.State)] $($finding.Repository)/$environmentLabel - $($finding.Code): $($finding.Message)")
    }
    foreach ($errorRecord in @($Report.Validation.QueryErrors)) {
        [void]$lines.Add("- [QUERY_ERROR] $($errorRecord.Repository)/$($errorRecord.Resource): $($errorRecord.Kind) (HTTP $($errorRecord.StatusCode))")
    }
    if (@($Report.Validation.Findings).Count -eq 0 -and @($Report.Validation.QueryErrors).Count -eq 0) {
        [void]$lines.Add('- Nenhum problema de configuracao retornado pelas consultas.')
    }
    [void]$lines.Add('')
    [void]$lines.Add('## Dependencias')
    [void]$lines.Add('')
    [void]$lines.Add('| Consumidor | Dependencia | Estado observavel | Run upstream |')
    [void]$lines.Add('|---|---|---|---:|')
    foreach ($dependency in @($Report.Dependencies)) {
        [void]$lines.Add("| $($dependency.Consumer) | $($dependency.Dependency) | $($dependency.State) | $(Format-AutoFlowOptionalValue $dependency.UpstreamRunId) |")
    }
    [void]$lines.Add('')
    [void]$lines.Add('## Proximas acoes manuais recomendadas')
    [void]$lines.Add('')
    foreach ($recommendation in @($Report.Recommendations)) { [void]$lines.Add("- $recommendation") }
    [void]$lines.Add('')
    [void]$lines.Add('A conclusao de uma pipeline nao prova que recursos AWS estejam provisionados. A ferramenta nao substitui aprovacoes nem gates das pipelines.')
    return ($lines -join [Environment]::NewLine)
}

function Write-AutoFlowReportFiles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Report,
        [string]$JsonPath,
        [string]$MarkdownPath
    )

    $targetPaths = New-Object System.Collections.Generic.List[string]
    foreach ($path in @($JsonPath, $MarkdownPath) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) {
        $fullPath = [System.IO.Path]::GetFullPath($path)
        if (($path -eq $JsonPath -and [System.IO.Path]::GetExtension($fullPath) -ine '.json') -or ($path -eq $MarkdownPath -and [System.IO.Path]::GetExtension($fullPath) -ine '.md')) {
            throw 'Extensao de arquivo de relatorio invalida.'
        }
        $parent = Split-Path -Parent $fullPath
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            throw "Diretorio de relatorio inexistente: $parent"
        }
        if (Test-Path -LiteralPath $fullPath) {
            throw 'O arquivo de relatorio ja existe; escolha outro caminho para preservar arquivos locais.'
        }
        if ($targetPaths.Contains($fullPath)) { throw 'JsonPath e MarkdownPath precisam ser diferentes.' }
        [void]$targetPaths.Add($fullPath)
    }
    if ($JsonPath) {
        $json = ConvertTo-Json -InputObject $Report -Depth 30
        [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($JsonPath), $json, (New-Object System.Text.UTF8Encoding($false)))
    }
    if ($MarkdownPath) {
        $markdown = ConvertTo-AutoFlowMarkdown $Report
        [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($MarkdownPath), $markdown, (New-Object System.Text.UTF8Encoding($false)))
    }
}

function Get-AutoFlowExitCode {
    param(
        [ValidateSet('status', 'validate', 'report')][string]$Action,
        $Status,
        $Validation
    )
    if ($Status -and $Status.HasQueryErrors) { return 3 }
    if ($Validation) {
        if ($Validation.HasQueryErrors -or $Validation.HasUnknown) { return 3 }
        if ($Validation.HasInconsistencies) { return 1 }
    }
    return 0
}

Export-ModuleMember -Function Format-AutoFlowStatusText, Format-AutoFlowValidationText, New-AutoFlowConsolidatedReport, ConvertTo-AutoFlowMarkdown, Write-AutoFlowReportFiles, Get-AutoFlowExitCode, New-AutoFlowDependencyStatus, New-AutoFlowRecommendations
