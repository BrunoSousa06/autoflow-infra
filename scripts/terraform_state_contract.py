"""Valida em conjunto os contratos externos dos seis Terraform roots."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ENVIRONMENTS = {"homolog", "production"}
ROOTS = {"vpc_eks", "rds", "lambda", "application", "api_gateway", "newrelic"}
CONSUMERS = {
    "rds": {"vpc_eks"},
    "lambda": {"vpc_eks", "rds"},
    "application": {"rds"},
    "api_gateway": {"vpc_eks"},
    "newrelic": {"vpc_eks"},
}
ACCOUNT_PATTERN = re.compile(r"[0-9]{12}\Z")
REGION_PATTERN = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+\Z")


class ContractError(ValueError):
    """Contrato de State integrado ausente ou inconsistente."""


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError(f"Configuração obrigatória ausente ou inválida: {label}.")
    return value


def validate_contract(document: dict[str, Any]) -> None:
    """Confirma isolamento, unicidade, ownership e referências entre os roots."""
    environments = document.get("environments")
    if not isinstance(environments, dict) or set(environments) != ENVIRONMENTS:
        raise ContractError("O contrato deve fornecer homolog e production explicitamente.")

    keys_by_environment: dict[str, set[str]] = {}
    for environment in sorted(ENVIRONMENTS):
        environment_config = environments[environment]
        roots = environment_config.get("roots") if isinstance(environment_config, dict) else None
        if not isinstance(roots, dict) or set(roots) != ROOTS:
            raise ContractError(f"Os seis Terraform roots devem estar configurados em {environment}.")

        prefix = f"{environment}/"
        keys: dict[str, str] = {}
        shared_identity: tuple[str, str, str] | None = None
        for root in sorted(ROOTS):
            root_config = roots[root]
            if not isinstance(root_config, dict):
                raise ContractError(f"Configuração inválida para um Terraform root de {environment}.")

            account = _required_string(root_config.get("account_id"), "account_id")
            bucket = _required_string(root_config.get("bucket"), "bucket")
            region = _required_string(root_config.get("region"), "region")
            key = _required_string(root_config.get("key"), "key")
            if ACCOUNT_PATTERN.fullmatch(account) is None:
                raise ContractError(f"Conta AWS inválida no Environment {environment}.")
            if REGION_PATTERN.fullmatch(region) is None:
                raise ContractError(f"Região AWS inválida no Environment {environment}.")
            if not key.startswith(prefix) or len(key) == len(prefix):
                raise ContractError(f"Key fora do prefixo obrigatório de {environment}.")
            if any(part in {"", ".", ".."} for part in key.split("/")):
                raise ContractError(f"Key com segmentos inválidos em {environment}.")

            identity = (account, bucket, region)
            if shared_identity is None:
                shared_identity = identity
            elif identity != shared_identity:
                raise ContractError(
                    f"Conta, bucket e região devem corresponder ao Environment {environment}."
                )
            keys[root] = key

        if len(set(keys.values())) != len(ROOTS):
            raise ContractError(f"As seis keys devem ser únicas no bucket de {environment}.")

        for consumer, producers in CONSUMERS.items():
            consumer_config = roots[consumer]
            references = consumer_config.get("consumes")
            if not isinstance(references, dict) or set(references) != producers:
                raise ContractError(f"Referências de State ausentes ou inesperadas em {environment}.")
            for producer in producers:
                if references[producer] != keys[producer]:
                    raise ContractError(
                        f"A key consumida não corresponde à key produtora em {environment}."
                    )

        keys_by_environment[environment] = set(keys.values())

    if keys_by_environment["homolog"] & keys_by_environment["production"]:
        raise ContractError("Homolog e production não podem compartilhar keys de State.")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="JSON externo com os seis roots dos dois Environments")
    options = parser.parse_args(arguments)
    try:
        with options.config.open(encoding="utf-8") as stream:
            document = json.load(stream)
        if not isinstance(document, dict):
            raise ContractError("A raiz do JSON precisa ser um objeto.")
        validate_contract(document)
    except (OSError, json.JSONDecodeError, ContractError) as error:
        print(f"Contrato Terraform bloqueado: {error}", file=sys.stderr)
        return 1

    print("Contrato integrado dos seis Terraform roots validado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
