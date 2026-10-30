Set-StrictMode -Version 2.0

$script:AutoFlowRepositories = @(
    [pscustomobject]@{
        Name = 'autoflow-infra'
        Owner = 'autoflow-fiap'
        Repository = 'autoflow-infra'
        FullName = 'autoflow-fiap/autoflow-infra'
        Branches = @{ homolog = 'develop'; production = 'main' }
        RequiredVariables = @(
            'AWS_EXPECTED_ACCOUNT_ID', 'AWS_REGION', 'AWS_TERRAFORM_STATE_BUCKET',
            'AWS_TF_STATE_KEY_INFRA', 'AWS_TF_STATE_KEY_GATEWAY', 'AWS_TF_STATE_KEY_NEWRELIC',
            'API_GATEWAY_CORS_ORIGINS', 'NEW_RELIC_REGION', 'TERRAFORM_APPLY_APPROVAL_CONFIGURED'
        )
        RequiredSecrets = @(
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
            'TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE', 'NEW_RELIC_API_KEY'
        )
    },
    [pscustomobject]@{
        Name = 'autoflow-db'
        Owner = 'autoflow-fiap'
        Repository = 'autoflow-db'
        FullName = 'autoflow-fiap/autoflow-db'
        Branches = @{ homolog = 'develop'; production = 'main' }
        RequiredVariables = @(
            'AWS_EXPECTED_ACCOUNT_ID', 'AWS_REGION', 'AWS_TERRAFORM_STATE_BUCKET',
            'AWS_TF_STATE_KEY', 'AWS_INFRA_STATE_KEY', 'TERRAFORM_APPLY_APPROVAL_CONFIGURED'
        )
        RequiredSecrets = @(
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
            'DATABASE_USERNAME', 'DATABASE_PASSWORD'
        )
    },
    [pscustomobject]@{
        Name = 'autoflow-lambda'
        Owner = 'autoflow-fiap'
        Repository = 'autoflow-lambda'
        FullName = 'autoflow-fiap/autoflow-lambda'
        Branches = @{ homolog = 'develop'; production = 'main' }
        RequiredVariables = @(
            'AWS_EXPECTED_ACCOUNT_ID', 'AWS_REGION', 'AWS_TERRAFORM_STATE_BUCKET',
            'AWS_TF_STATE_KEY', 'AWS_INFRA_STATE_KEY', 'AWS_RDS_STATE_KEY',
            'AWS_LAMBDA_EXECUTION_ROLE_ARN', 'TERRAFORM_APPLY_APPROVAL_CONFIGURED'
        )
        RequiredSecrets = @(
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
            'DATABASE_USERNAME', 'DATABASE_PASSWORD', 'JWT_SECRET'
        )
    },
    [pscustomobject]@{
        Name = 'autoflow'
        Owner = 'autoflow-fiap'
        Repository = 'autoflow'
        FullName = 'autoflow-fiap/autoflow'
        Branches = @{ homolog = 'develop'; production = 'main' }
        RequiredVariables = @(
            'AWS_EXPECTED_ACCOUNT_ID', 'AWS_REGION', 'AWS_TERRAFORM_STATE_BUCKET',
            'AWS_TF_STATE_KEY', 'API_GATEWAY_CORS_ORIGINS',
            'TERRAFORM_APPLY_APPROVAL_CONFIGURED'
        )
        RequiredSecrets = @(
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
            'TF_PLAN_ENCRYPTION_KEY', 'AUTOFLOW_DB_USERNAME', 'AUTOFLOW_DB_PASSWORD',
            'AUTOFLOW_JWT_SECRET', 'AUTOFLOW_MAIL_PASSWORD', 'AUTOFLOW_PUBLIC_TOKEN_SECRET'
        )
    }
)

$script:AutoFlowStateRoots = @(
    [pscustomobject]@{
        Name = 'vpc_eks'
        Repository = 'autoflow-infra'
        KeyVariable = 'AWS_TF_STATE_KEY_INFRA'
        ConsumeVariables = @{}
        ConsumeDefaults = @{}
    },
    [pscustomobject]@{
        Name = 'rds'
        Repository = 'autoflow-db'
        KeyVariable = 'AWS_TF_STATE_KEY'
        ConsumeVariables = @{ vpc_eks = 'AWS_INFRA_STATE_KEY' }
        ConsumeDefaults = @{}
    },
    [pscustomobject]@{
        Name = 'lambda'
        Repository = 'autoflow-lambda'
        KeyVariable = 'AWS_TF_STATE_KEY'
        ConsumeVariables = @{ vpc_eks = 'AWS_INFRA_STATE_KEY'; rds = 'AWS_RDS_STATE_KEY' }
        ConsumeDefaults = @{}
    },
    [pscustomobject]@{
        Name = 'application'
        Repository = 'autoflow'
        KeyVariable = 'AWS_TF_STATE_KEY'
        # This is the current default of autoflow/infra/vars.tf; the workflow does not override it.
        ConsumeDefaults = @{ rds = 'rds/terraform.tfstate' }
        ConsumeVariables = @{}
    },
    [pscustomobject]@{
        Name = 'api_gateway'
        Repository = 'autoflow-infra'
        KeyVariable = 'AWS_TF_STATE_KEY_GATEWAY'
        ConsumeVariables = @{ vpc_eks = 'AWS_TF_STATE_KEY_INFRA' }
        ConsumeDefaults = @{}
    },
    [pscustomobject]@{
        Name = 'newrelic'
        Repository = 'autoflow-infra'
        KeyVariable = 'AWS_TF_STATE_KEY_NEWRELIC'
        ConsumeVariables = @{ vpc_eks = 'AWS_TF_STATE_KEY_INFRA' }
        ConsumeDefaults = @{}
    }
)

function Get-AutoFlowRepositories {
    return $script:AutoFlowRepositories
}

function Get-AutoFlowStateRoots {
    return $script:AutoFlowStateRoots
}

function Get-AutoFlowEnvironmentNames {
    return @('homolog', 'production')
}

function Get-AutoFlowQueryPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidateSet('status', 'validate', 'report')][string]$Action,
        [Parameter(Mandatory = $true)][ValidateSet('homolog', 'production')][string]$Environment
    )

    $queries = New-Object System.Collections.Generic.List[string]
    foreach ($repository in $script:AutoFlowRepositories) {
        [void]$queries.Add("GET /repos/$($repository.FullName)")
        if ($Action -eq 'status' -or $Action -eq 'report') {
            $branch = $repository.Branches[$Environment]
            [void]$queries.Add("GET /repos/$($repository.FullName)/branches/$branch")
            [void]$queries.Add("GET /repos/$($repository.FullName)/actions/workflows")
            [void]$queries.Add("GET /repos/$($repository.FullName)/actions/workflows/{workflow_id}/runs?branch=$branch")
            [void]$queries.Add("GET /repos/$($repository.FullName)/actions/runs/{run_id}/jobs")
            [void]$queries.Add("GET /repos/$($repository.FullName)/actions/runs/{run_id}/pending_deployments (when run/job status is waiting)")
        }
        if ($Action -eq 'validate' -or $Action -eq 'report') {
            [void]$queries.Add("GET /repos/$($repository.FullName)/environments (inventory for confirmed absence)")
            foreach ($environmentName in (Get-AutoFlowEnvironmentNames)) {
                [void]$queries.Add("GET /repos/$($repository.FullName)/environments/$environmentName")
                [void]$queries.Add("GET /repos/$($repository.FullName)/environments/$environmentName/variables")
                [void]$queries.Add("GET /repos/$($repository.FullName)/environments/$environmentName/secrets (names only)")
                [void]$queries.Add("GET /repos/$($repository.FullName)/branches/$($repository.Branches[$environmentName])")
                [void]$queries.Add("GET /repos/$($repository.FullName)/environments/$environmentName/deployment-branch-policies (when custom policy is enabled)")
            }
        }
    }
    return $queries.ToArray()
}

Export-ModuleMember -Function Get-AutoFlowRepositories, Get-AutoFlowStateRoots, Get-AutoFlowEnvironmentNames, Get-AutoFlowQueryPlan
