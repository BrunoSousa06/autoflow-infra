"""Resolve o bucket compartilhado de Terraform State."""

from __future__ import annotations

import os
import re
import sys


ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")
REGION_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*-\d\Z")


def resolve_state_bucket(configured_bucket: str | None, expected_account: str | None, region: str | None) -> str:
    """Prioriza o nome externo; deriva o nome Learner Lab somente se ausente."""
    if configured_bucket and configured_bucket.strip():
        return configured_bucket.strip()
    if not expected_account or ACCOUNT_ID_PATTERN.fullmatch(expected_account) is None:
        raise ValueError("AWS_EXPECTED_ACCOUNT_ID ausente ou inválido para derivar o bucket.")
    if not region or REGION_PATTERN.fullmatch(region) is None:
        raise ValueError("AWS_REGION ausente ou inválida para derivar o bucket.")
    return f"autoflow-tfstate-learnerlab-{expected_account}-{region}"


def main() -> int:
    try:
        bucket = resolve_state_bucket(
            os.environ.get("AWS_TERRAFORM_STATE_BUCKET"),
            os.environ.get("AWS_EXPECTED_ACCOUNT_ID"),
            os.environ.get("AWS_REGION"),
        )
    except ValueError as error:
        print(f"Resolução do bucket de State bloqueada: {error}", file=sys.stderr)
        return 1
    print(bucket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
