"""Calcula fingerprint sem revelar as configurações de backend e recursos."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


FIELDS = {
    "vpc-eks": (
        "GITHUB_DEPLOYMENT_ENVIRONMENT",
        "AWS_EXPECTED_ACCOUNT_ID",
        "AWS_REGION",
        "TF_STATE_BUCKET",
        "TF_STATE_KEY",
        "TF_VAR_project_name",
        "TF_VAR_region_default",
        "TF_VAR_aws_allowed_account_ids",
        "EKS_CLUSTER_NAME",
        "EKS_LEASE_BUCKET",
        "EKS_LEASE_KEY",
        "ALLOW_DESTRUCTIVE",
        "ALLOW_EKS_STATE_RECONCILIATION",
        "TF_VAR_cidr_vpc",
        "TF_VAR_instance_type",
        "TF_VAR_node_min_size",
        "TF_VAR_node_desired_size",
        "TF_VAR_node_max_size",
        "TF_VAR_cluster_endpoint_private_access",
        "TF_VAR_cluster_endpoint_public_access",
        "TF_VAR_cluster_endpoint_public_access_cidrs",
        "TF_VAR_create_nat_gateway",
        "TF_VAR_create_operator_access_entry",
    ),
    "api-gateway": (
        "GITHUB_DEPLOYMENT_ENVIRONMENT",
        "AWS_EXPECTED_ACCOUNT_ID",
        "AWS_REGION",
        "TF_VAR_terraform_state_bucket",
        "TF_STATE_KEY",
        "TF_VAR_infra_state_key",
        "AWS_TF_STATE_KEY_NEWRELIC",
        "TF_VAR_environment",
        "TF_VAR_lambda_function_name",
        "EKS_PROJECT_NAME",
        "EKS_CLUSTER_NAME",
        "EKS_NODEGROUP_NAME",
        "TF_VAR_cors_origins",
        "TF_VAR_enable_detailed_gateway_metrics",
    ),
}
REQUIRED = {
    "vpc-eks": {
        "GITHUB_DEPLOYMENT_ENVIRONMENT",
        "AWS_EXPECTED_ACCOUNT_ID",
        "AWS_REGION",
        "TF_STATE_BUCKET",
        "TF_STATE_KEY",
        "TF_VAR_project_name",
        "TF_VAR_region_default",
        "TF_VAR_aws_allowed_account_ids",
        "EKS_CLUSTER_NAME",
        "EKS_LEASE_BUCKET",
        "EKS_LEASE_KEY",
    },
    "api-gateway": {
        "GITHUB_DEPLOYMENT_ENVIRONMENT",
        "AWS_EXPECTED_ACCOUNT_ID",
        "AWS_REGION",
        "TF_VAR_terraform_state_bucket",
        "TF_STATE_KEY",
        "TF_VAR_infra_state_key",
        "AWS_TF_STATE_KEY_NEWRELIC",
        "TF_VAR_environment",
        "TF_VAR_lambda_function_name",
        "EKS_CLUSTER_NAME",
        "EKS_NODEGROUP_NAME",
        "TF_VAR_cors_origins",
    },
}


class FingerprintError(ValueError):
    """Fingerprint ausente, inválido ou divergente."""


def calculate_fingerprint(root: str, values: dict[str, str]) -> str:
    if root not in FIELDS:
        raise FingerprintError("Root Terraform não reconhecido para fingerprint.")
    if any(not values.get(name, "").strip() for name in REQUIRED[root]):
        raise FingerprintError("Configuração necessária ao fingerprint ausente.")
    canonical = {name: values.get(name, "") for name in FIELDS[root]}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_fingerprint(root: str, values: dict[str, str], expected: str) -> None:
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise FingerprintError("Fingerprint esperado ausente ou inválido.")
    if calculate_fingerprint(root, values) != expected:
        raise FingerprintError("Configuração do Apply diverge da configuração usada no Plan.")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", choices=sorted(FIELDS))
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("path", type=Path, help="Arquivo local com o SHA-256 do fingerprint")
    options = parser.parse_args(arguments)
    try:
        fingerprint = calculate_fingerprint(options.root, dict(os.environ))
        if options.mode == "create":
            options.path.write_text(f"{fingerprint}\n", encoding="ascii")
        else:
            validate_fingerprint(
                options.root,
                dict(os.environ),
                options.path.read_text(encoding="ascii").strip(),
            )
    except (OSError, FingerprintError) as error:
        print(f"Fingerprint Terraform bloqueado: {error}", file=sys.stderr)
        return 1
    print(f"Fingerprint do root {options.root} {options.mode} validado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
