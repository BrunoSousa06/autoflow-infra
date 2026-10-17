"""Gera import declarativo do VPC Link existente sem State próprio do Gateway."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


VPC_LINK_ADDRESS = "module.private_eks.aws_apigatewayv2_vpc_link.this"


def missing_state_error(error):
    text = "\n".join((error.stdout or "", error.stderr or "")).lower()
    return "no state file was found" in text or "no state found" in text


def state_addresses(bucket, key):
    try:
        result = subprocess.run(["terraform", "-chdir=infra/api-gateway", "state", "list"],
                                check=True, capture_output=True, text=True)
        return set(result.stdout.splitlines())
    except subprocess.CalledProcessError as error:
        if missing_state_error(error):
            return set()
        try:
            subprocess.run(["aws", "s3api", "head-object", "--bucket", bucket, "--key", key],
                           check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as state_error:
            message = "\n".join((state_error.stdout or "", state_error.stderr or "")).lower()
            if "nosuchkey" in message or "404" in message:
                return set()
            raise RuntimeError("Falha ao verificar o State do API Gateway no S3; verifique credenciais e permissões.") from state_error
        raise RuntimeError("Terraform não conseguiu ler o State do API Gateway, embora o objeto exista.") from error


def discover_imports(addresses, links, expected_name):
    if VPC_LINK_ADDRESS in addresses:
        return []
    matching = [link for link in links if link.get("Name") == expected_name]
    if len(matching) > 1:
        raise RuntimeError(f"Há múltiplos VPC Links chamados {expected_name}; import automático bloqueado.")
    if not matching:
        return []
    link_id = matching[0].get("VpcLinkId")
    if not isinstance(link_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", link_id) is None:
        raise RuntimeError("AWS retornou VPC Link sem identificador válido; import bloqueado.")
    return [(VPC_LINK_ADDRESS, link_id)]


def render_imports(imports):
    return "\n".join(
        f'import {{\n  to = {address}\n  id = "{link_id}"\n}}'
        for address, link_id in imports
    ) + ("\n" if imports else "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = subprocess.run(["aws", "apigatewayv2", "get-vpc-links", "--region", args.region,
                                 "--output", "json"], check=True, capture_output=True, text=True)
        links = json.loads(result.stdout or "{}").get("Items", [])
        imports = discover_imports(state_addresses(args.bucket, args.key), links, args.name)
        Path(args.output).write_text(render_imports(imports), encoding="utf-8")
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Falha AWS ao consultar VPC Links; verifique credenciais e permissões.") from error
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Falha ao preparar import do VPC Link: {error}") from error
    print(f"Imports declarativos do VPC Link: {len(imports)}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
