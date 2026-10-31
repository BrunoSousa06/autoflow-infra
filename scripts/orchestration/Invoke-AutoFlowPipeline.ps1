[CmdletBinding()]
param(
    [string]$Environment = '',

    [string]$Action = '',

    [switch]$DryRun,
    [string]$JsonPath,
    [string]$MarkdownPath
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
if ($Environment -notin @('homolog', 'production')) {
    [Console]::Error.WriteLine('Environment deve ser homolog ou production.')
    exit 2
}
if ($Action -notin @('status', 'validate', 'report')) {
    [Console]::Error.WriteLine('Action deve ser status, validate ou report.')
    exit 2
}

$moduleRoot = $PSScriptRoot
Import-Module (Join-Path $moduleRoot 'AutoFlow.Config.psm1') -Force
Import-Module (Join-Path $moduleRoot 'AutoFlow.GitHub.psm1') -Force
Import-Module (Join-Path $moduleRoot 'AutoFlow.Validation.psm1') -Force
Import-Module (Join-Path $moduleRoot 'AutoFlow.Reporting.psm1') -Force

if (($JsonPath -or $MarkdownPath) -and $Action -ne 'report') {
    [Console]::Error.WriteLine('JsonPath e MarkdownPath so permitidos com -Action report.')
    exit 2
}
if ($JsonPath -and [System.IO.Path]::GetExtension($JsonPath) -ine '.json') {
    [Console]::Error.WriteLine('JsonPath deve terminar em .json.')
    exit 2
}
if ($MarkdownPath -and [System.IO.Path]::GetExtension($MarkdownPath) -ine '.md') {
    [Console]::Error.WriteLine('MarkdownPath deve terminar em .md.')
    exit 2
}
foreach ($reportPath in @($JsonPath, $MarkdownPath) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) {
    try {
        $absoluteReportPath = [System.IO.Path]::GetFullPath($reportPath)
    } catch {
        [Console]::Error.WriteLine('Caminho de relatorio invalido.')
        exit 2
    }
    $reportDirectory = Split-Path -Parent $absoluteReportPath
    if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) {
        [Console]::Error.WriteLine('O diretorio de relatorio precisa existir.')
        exit 2
    }
    if (Test-Path -LiteralPath $absoluteReportPath) {
        [Console]::Error.WriteLine('O arquivo de relatorio ja existe; escolha outro caminho para preservar arquivos locais.')
        exit 2
    }
}
if ($DryRun -and ($JsonPath -or $MarkdownPath)) {
    [Console]::Error.WriteLine('DryRun nao grava arquivos de relatorio.')
    exit 2
}

try {
    if ($DryRun) {
        Write-Output "Dry-run: consultas planejadas para -Environment $Environment -Action $Action; nenhuma consulta foi executada."
        foreach ($query in (Get-AutoFlowQueryPlan -Action $Action -Environment $Environment)) {
            Write-Output "  $query"
        }
        exit 0
    }

    $status = $null
    $validation = $null
    if ($Action -eq 'status' -or $Action -eq 'report') {
        $status = Get-AutoFlowStatus -Environment $Environment
        Write-Output (Format-AutoFlowStatusText $status)
    }
    if ($Action -eq 'validate' -or $Action -eq 'report') {
        $validation = Invoke-AutoFlowValidation -Environment $Environment
        Write-Output (Format-AutoFlowValidationText $validation)
    }
    if ($Action -eq 'report') {
        $report = New-AutoFlowConsolidatedReport -Status $status -Validation $validation
        if ($JsonPath -or $MarkdownPath) {
            Write-AutoFlowReportFiles -Report $report -JsonPath $JsonPath -MarkdownPath $MarkdownPath
            if ($JsonPath) { Write-Output "JSON local gravado: $([System.IO.Path]::GetFullPath($JsonPath))" }
            if ($MarkdownPath) { Write-Output "Markdown local gravado: $([System.IO.Path]::GetFullPath($MarkdownPath))" }
        }
    }
    $exitCode = Get-AutoFlowExitCode -Action $Action -Status $status -Validation $validation
    exit $exitCode
} catch {
    [Console]::Error.WriteLine("Erro do orquestrador: $($_.Exception.Message)")
    exit 3
}
