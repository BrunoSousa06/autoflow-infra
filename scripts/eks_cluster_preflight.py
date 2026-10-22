"""Detecta cluster EKS ausente sem tratar falhas AWS como ausência."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


class PreflightError(RuntimeError):
    """A consulta ao EKS falhou por motivo diferente de cluster inexistente."""


def cluster_exists(cluster: str, region: str, run=None) -> bool:
    run = subprocess.run if run is None else run
    try:
        result = run(
            ["aws", "eks", "describe-cluster", "--name", cluster, "--region", region,
             "--query", "cluster.name", "--output", "text"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        message = (error.stderr or "").lower()
        if "resourcenotfoundexception" in message or "resource not found" in message:
            return False
        raise PreflightError(
            "Não foi possível confirmar a existência do EKS; erro AWS/permissão bloqueia o Plan/Apply."
        ) from error
    except OSError as error:
        raise PreflightError("AWS CLI indisponível para consultar o cluster EKS.") from error

    return bool(result.stdout.strip()) and result.stdout.strip().lower() not in {"none", "null"}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args(arguments)
    try:
        exists = cluster_exists(args.cluster, args.region)
        value = "true" if exists else "false"
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"exists={value}\n")
        print(f"Cluster EKS existente: {value}.")
        return 0
    except PreflightError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
