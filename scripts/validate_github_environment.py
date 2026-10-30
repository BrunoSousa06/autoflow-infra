"""Valida, antes de acessar AWS, os valores injetados pelo GitHub Environment."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping, Sequence


AWS_ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")
AWS_REGION_PATTERN = re.compile(r"[a-z]{2}(-gov)?-[a-z]+-[0-9]+\Z")
SUPPORTED_ENVIRONMENTS = {"homolog", "production"}


class ConfigurationError(ValueError):
    """Configuração obrigatória ausente ou incompatível com o Environment."""


def validate_configuration(
    environment_name: str,
    values: Mapping[str, str],
    required_variables: Sequence[str],
    required_secrets: Sequence[str],
    state_keys: Sequence[str] = (),
    require_approval_gate: bool = False,
) -> None:
    """Falha sem revelar valores se inputs estiverem vazios ou cruzarem ambientes."""
    if environment_name not in SUPPORTED_ENVIRONMENTS:
        raise ConfigurationError("Environment deve ser homolog ou production.")

    variables = tuple(dict.fromkeys((
        "AWS_EXPECTED_ACCOUNT_ID",
        "AWS_REGION",
        "AWS_TERRAFORM_STATE_BUCKET",
        *required_variables,
    )))
    for name in variables:
        if not values.get(name, "").strip():
            raise ConfigurationError(f"Variable {name} ausente ou vazia no Environment selecionado.")

    for name in dict.fromkeys(required_secrets):
        if not values.get(name, "").strip():
            raise ConfigurationError(f"Secret {name} ausente ou vazio no Environment selecionado.")

    if AWS_ACCOUNT_ID_PATTERN.fullmatch(values["AWS_EXPECTED_ACCOUNT_ID"].strip()) is None:
        raise ConfigurationError("AWS_EXPECTED_ACCOUNT_ID deve conter 12 dígitos.")
    if AWS_REGION_PATTERN.fullmatch(values["AWS_REGION"].strip()) is None:
        raise ConfigurationError("AWS_REGION possui formato inválido.")

    prefix = f"{environment_name}/"
    resolved_keys: list[str] = []
    for name in state_keys:
        key = values.get(name, "").strip()
        if not key.startswith(prefix) or not key[len(prefix) :].strip("/"):
            raise ConfigurationError(f"{name} deve ser uma State Key não vazia prefixada por {prefix}.")
        resolved_keys.append(key)
    if len(resolved_keys) != len(set(resolved_keys)):
        raise ConfigurationError("As State Keys do Environment devem ser exclusivas entre roots.")

    if require_approval_gate and values.get("TERRAFORM_APPLY_APPROVAL_CONFIGURED", "").strip() != "true":
        raise ConfigurationError("TERRAFORM_APPLY_APPROVAL_CONFIGURED deve ser true após auditoria externa dos reviewers.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--variable", action="append", default=[], dest="variables")
    parser.add_argument("--secret", action="append", default=[], dest="secrets")
    parser.add_argument("--state-key", action="append", default=[], dest="state_keys")
    parser.add_argument("--approval-gate", action="store_true")
    args = parser.parse_args()

    try:
        validate_configuration(
            args.environment,
            os.environ,
            args.variables,
            args.secrets,
            args.state_keys,
            args.approval_gate,
        )
    except ConfigurationError as error:
        print(error, file=sys.stderr)
        return 1

    print("Configuração obrigatória do GitHub Environment válida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
