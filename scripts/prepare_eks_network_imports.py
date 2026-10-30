"""Prepara imports declarativos de rede EKS com ownership inequívoco."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from prepare_eks_access_imports import state_addresses
from eks_cluster_preflight import PreflightError, cluster_exists


ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")
PRIVATE_SUBNETS = (
    (0, "10.0.64.0/20", "us-east-1a"),
    (1, "10.0.80.0/20", "us-east-1b"),
    (2, "10.0.96.0/20", "us-east-1c"),
)
PUBLIC_SUBNETS = (
    (0, "10.0.0.0/20", "us-east-1a"),
    (1, "10.0.16.0/20", "us-east-1b"),
    (2, "10.0.32.0/20", "us-east-1c"),
)
VPC_ADDRESS = "aws_vpc.autoflow_vpc"
ROUTE_TABLE_ADDRESS = "aws_route_table.route_table_private"


class NetworkImportError(RuntimeError):
    """A reconciliação não pode ser determinada com segurança."""


def run_json(command: list[str], run: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    try:
        result = run(command, check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise NetworkImportError(
            "Consulta AWS/Terraform inconclusiva durante descoberta de ownership; reconciliação bloqueada."
        ) from error
    if not isinstance(payload, dict):
        raise NetworkImportError("Resposta AWS inesperada durante descoberta de ownership.")
    return payload


def state_resource_ids(addresses: set[str], run: Callable[..., Any] = subprocess.run) -> dict[str, str]:
    """Lê somente IDs de endereços gerenciados para impedir import sobre ID divergente."""
    relevant = {VPC_ADDRESS, ROUTE_TABLE_ADDRESS}
    relevant.update(f"aws_subnet.subnet_private[{index}]" for index, _, _ in PRIVATE_SUBNETS)
    relevant.update(f"aws_route_table_association.private_association[{index}]" for index, _, _ in PRIVATE_SUBNETS)
    relevant.update(f"aws_subnet.subnet_public[{index}]" for index, _, _ in PUBLIC_SUBNETS)
    relevant.update(("aws_route_table.route_table", "aws_internet_gateway.igw", "aws_eip.nat_eip[0]",
                     "aws_nat_gateway.nat[0]", "aws_security_group.sg", "aws_eks_cluster.autoflow",
                     "aws_eks_node_group.node_group"))
    relevant.update(f"aws_route_table_association.route_table_association[{index}]" for index, _, _ in PUBLIC_SUBNETS)
    result: dict[str, str] = {}
    for address in sorted(addresses & relevant):
        try:
            shown = run(
                ["terraform", "-chdir=infra", "state", "show", "-no-color", address],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise NetworkImportError(
                f"Não foi possível conferir o ID já registrado em {address}; reconciliação bloqueada."
            ) from error
        match = re.search(r'^\s*id\s*=\s*"([^"]+)"\s*$', shown.stdout, re.MULTILINE)
        if match is None:
            raise NetworkImportError(
                f"State não expõe um ID verificável para {address}; reconciliação bloqueada."
            )
        result[address] = match.group(1)
    return result


def _tag_map(resource: dict[str, Any]) -> dict[str, str]:
    return {
        item.get("Key"): item.get("Value")
        for item in resource.get("Tags", [])
        if isinstance(item, dict) and isinstance(item.get("Key"), str)
    }


def _add_import(
    imports: list[tuple[str, str]],
    state_ids: dict[str, str],
    addresses: set[str],
    address: str,
    import_id: str,
    observed_id: str | None = None,
) -> None:
    if address in addresses:
        if observed_id is not None and state_ids.get(address) != observed_id:
            raise NetworkImportError(
                f"O endereço {address} já contém um recurso diferente; reconciliação bloqueada."
            )
        return
    imports.append((address, import_id))


def _reject_untracked_survivor(
    address: str, observed_id: str, addresses: set[str], state_ids: dict[str, str]
) -> None:
    if address not in addresses:
        raise NetworkImportError(
            f"Recurso {address} existe fora do State, mas está fora do conjunto de imports automáticos suportados; Plan bloqueado."
        )
    if state_ids.get(address) != observed_id:
        raise NetworkImportError(f"O endereço {address} aponta para ID divergente; Plan bloqueado.")


def discover_imports(
    expected_account: str,
    region: str,
    addresses: set[str],
    state_ids: dict[str, str],
    run: Callable[..., Any] = subprocess.run,
    project_name: str = "autoflow",
) -> list[tuple[str, str]]:
    if (ACCOUNT_ID_PATTERN.fullmatch(expected_account or "") is None or not region
            or re.fullmatch(r"[a-z][a-z0-9-]*", project_name or "") is None):
        raise NetworkImportError("Conta, região e nome de projeto válidos são obrigatórios.")
    vpc_name = "main-vpc" if project_name == "autoflow" else f"main-vpc-{project_name}"
    cluster_name = f"eks-{project_name}"
    nodegroup_name = f"nodeg-{project_name}"
    aws = ["aws"]
    vpcs = run_json(
        aws + ["ec2", "describe-vpcs", "--region", region, "--filters", f"Name=tag:Name,Values={vpc_name}"],
        run,
    ).get("Vpcs")
    if not isinstance(vpcs, list):
        raise NetworkImportError("DescribeVpcs retornou resposta incompleta.")
    if not vpcs:
        return []
    if len(vpcs) != 1:
        raise NetworkImportError(f"Mais de uma VPC candidata {vpc_name}; reconciliação ambígua.")
    vpc = vpcs[0]
    vpc_id = vpc.get("VpcId")
    if (not isinstance(vpc_id, str) or vpc.get("OwnerId") != expected_account
            or vpc.get("CidrBlock") != "10.0.0.0/16" or _tag_map(vpc).get("Name") != vpc_name):
        raise NetworkImportError("VPC candidata não corresponde a owner/CIDR/tag do root Terraform.")

    for attribute in ("enableDnsSupport", "enableDnsHostnames"):
        response = run_json(
            aws + ["ec2", "describe-vpc-attribute", "--vpc-id", vpc_id, "--attribute", attribute,
                   "--region", region],
            run,
        )
        if response.get("EnableDnsSupport" if attribute == "enableDnsSupport" else "EnableDnsHostnames", {}).get("Value") is not True:
            raise NetworkImportError(f"A VPC não corresponde ao atributo Terraform {attribute}.")

    imports: list[tuple[str, str]] = []
    _add_import(imports, state_ids, addresses, VPC_ADDRESS, vpc_id, vpc_id)

    subnets = run_json(
        aws + ["ec2", "describe-subnets", "--region", region, "--filters", f"Name=vpc-id,Values={vpc_id}"],
        run,
    ).get("Subnets")
    if not isinstance(subnets, list):
        raise NetworkImportError("DescribeSubnets retornou resposta incompleta.")
    subnet_ids: dict[int, str] = {}
    for index, cidr, zone in PRIVATE_SUBNETS:
        candidates = [item for item in subnets if item.get("CidrBlock") == cidr]
        address = f"aws_subnet.subnet_private[{index}]"
        if len(candidates) > 1:
            raise NetworkImportError(f"Mais de uma subnet candidata para {cidr}; import ambíguo.")
        if not candidates:
            continue
        subnet = candidates[0]
        tags = _tag_map(subnet)
        if (subnet.get("VpcId") != vpc_id or subnet.get("OwnerId") != expected_account
                or subnet.get("AvailabilityZone") != zone or subnet.get("MapPublicIpOnLaunch") is not False
                or tags.get("Name") != "private-subnet"
                or tags.get("kubernetes.io/role/internal-elb") != "1"
                or tags.get(f"kubernetes.io/cluster/{cluster_name}") != "shared"):
            raise NetworkImportError(f"Subnet {cidr} não corresponde integralmente à declaração privada Terraform.")
        subnet_id = subnet.get("SubnetId")
        if not isinstance(subnet_id, str):
            raise NetworkImportError(f"Subnet {cidr} não retornou ID válido.")
        subnet_ids[index] = subnet_id
        _add_import(imports, state_ids, addresses, address, subnet_id, subnet_id)

    for index, cidr, zone in PUBLIC_SUBNETS:
        candidates = [item for item in subnets if item.get("CidrBlock") == cidr]
        if len(candidates) > 1:
            raise NetworkImportError(f"Mais de uma subnet candidata para {cidr}; import ambíguo.")
        if candidates:
            subnet = candidates[0]
            subnet_id = subnet.get("SubnetId")
            tags = _tag_map(subnet)
            if (subnet.get("VpcId") != vpc_id or subnet.get("OwnerId") != expected_account
                    or subnet.get("AvailabilityZone") != zone or subnet.get("MapPublicIpOnLaunch") is not True
                    or tags.get("Name") != "public-subnet"
                    or tags.get("kubernetes.io/role/elb") != "1"
                    or tags.get(f"kubernetes.io/cluster/{cluster_name}") != "shared"):
                raise NetworkImportError(f"Subnet pública {cidr} não corresponde à declaração Terraform.")
            _reject_untracked_survivor(
                f"aws_subnet.subnet_public[{index}]", subnet_id, addresses, state_ids
            )

    route_tables = run_json(
        aws + ["ec2", "describe-route-tables", "--region", region, "--filters", f"Name=vpc-id,Values={vpc_id}"],
        run,
    ).get("RouteTables")
    if not isinstance(route_tables, list):
        raise NetworkImportError("DescribeRouteTables retornou resposta incompleta.")

    gateway_response = run_json(
        aws + ["ec2", "describe-internet-gateways", "--region", region,
               "--filters", f"Name=attachment.vpc-id,Values={vpc_id}"],
        run,
    )
    gateways = gateway_response.get("InternetGateways")
    if not isinstance(gateways, list):
        raise NetworkImportError("DescribeInternetGateways retornou resposta incompleta.")
    if len(gateways) > 1:
        raise NetworkImportError("Mais de um Internet Gateway ligado à VPC; ownership ambíguo.")
    if gateways:
        gateway = gateways[0]
        gateway_id = gateway.get("InternetGatewayId")
        attachments = gateway.get("Attachments", [])
        if (not isinstance(gateway_id, str) or gateway.get("OwnerId") != expected_account
                or not any(item.get("VpcId") == vpc_id and item.get("State") == "available" for item in attachments)):
            raise NetworkImportError("Internet Gateway não corresponde à VPC/conta esperada.")
        _reject_untracked_survivor("aws_internet_gateway.igw", gateway_id, addresses, state_ids)

    public_route_table_name = f"{project_name}-public-rt"
    public_route_tables = [item for item in route_tables if _tag_map(item).get("Name") == public_route_table_name]
    if len(public_route_tables) > 1:
        raise NetworkImportError(f"Mais de uma route table {public_route_table_name}; ownership ambíguo.")
    if public_route_tables:
        table = public_route_tables[0]
        table_id = table.get("RouteTableId")
        if table.get("OwnerId") != expected_account or not isinstance(table_id, str):
            raise NetworkImportError("Route table pública não pertence à conta esperada.")
        default_routes = [item for item in table.get("Routes", []) if item.get("DestinationCidrBlock") == "0.0.0.0/0"]
        if len(default_routes) != 1 or not gateways or default_routes[0].get("GatewayId") != gateways[0].get("InternetGatewayId"):
            raise NetworkImportError("Route table pública não tem rota default inequívoca para o IGW da VPC.")
        _reject_untracked_survivor("aws_route_table.route_table", table_id, addresses, state_ids)

    eips = run_json(
        aws + ["ec2", "describe-addresses", "--region", region,
               "--filters", f"Name=tag:Name,Values={project_name}-nat-eip"],
        run,
    ).get("Addresses")
    if not isinstance(eips, list):
        raise NetworkImportError("DescribeAddresses retornou resposta incompleta.")
    if len(eips) > 1:
        raise NetworkImportError(f"Mais de um EIP {project_name}-nat-eip; ownership ambíguo.")
    if eips:
        eip = eips[0]
        allocation_id = eip.get("AllocationId")
        if eip.get("Domain") != "vpc" or _tag_map(eip).get("Name") != f"{project_name}-nat-eip" or not allocation_id:
            raise NetworkImportError("EIP candidato não corresponde à declaração Terraform.")
        _reject_untracked_survivor("aws_eip.nat_eip[0]", allocation_id, addresses, state_ids)

    nat_gateways = run_json(
        aws + ["ec2", "describe-nat-gateways", "--region", region,
               "--filter", f"Name=vpc-id,Values={vpc_id}"],
        run,
    ).get("NatGateways")
    if not isinstance(nat_gateways, list):
        raise NetworkImportError("DescribeNatGateways retornou resposta incompleta.")
    if len(nat_gateways) > 1:
        raise NetworkImportError("Há NAT Gateways na VPC; ownership não é unívoco para o NAT declarado.")
    if nat_gateways:
        nat = nat_gateways[0]
        nat_id = nat.get("NatGatewayId")
        allocations = [item.get("AllocationId") for item in nat.get("NatGatewayAddresses", [])]
        if (nat.get("VpcId") != vpc_id or nat.get("State") not in {"available", "pending"}
                or _tag_map(nat).get("Name") != f"{project_name}-nat-gateway" or not isinstance(nat_id, str)):
            raise NetworkImportError("NAT Gateway candidato não corresponde à declaração Terraform.")
        if eips and allocations != [eips[0].get("AllocationId")]:
            raise NetworkImportError(f"NAT Gateway não usa o EIP {project_name}-nat-eip observado.")
        _reject_untracked_survivor("aws_nat_gateway.nat[0]", nat_id, addresses, state_ids)

    groups = run_json(
        aws + ["ec2", "describe-security-groups", "--region", region,
                "--filters", f"Name=vpc-id,Values={vpc_id}", f"Name=group-name,Values={project_name}-sg"],
        run,
    ).get("SecurityGroups")
    if not isinstance(groups, list):
        raise NetworkImportError("DescribeSecurityGroups retornou resposta incompleta.")
    if len(groups) > 1:
        raise NetworkImportError(f"Mais de um security group {project_name}-sg; ownership ambíguo.")
    if groups:
        group = groups[0]
        group_id = group.get("GroupId")
        egress = group.get("IpPermissionsEgress", [])
        if (group.get("OwnerId") != expected_account or group.get("VpcId") != vpc_id
                or group.get("Description") != "Security group for EKS cluster"
                or group.get("IpPermissions") or len(egress) != 1
                or egress[0].get("IpProtocol") != "-1"
                or not any(item.get("CidrIp") == "0.0.0.0/0" for item in egress[0].get("IpRanges", []))
                or not isinstance(group_id, str)):
            raise NetworkImportError(f"Security group {project_name}-sg não corresponde à declaração Terraform.")
        _reject_untracked_survivor("aws_security_group.sg", group_id, addresses, state_ids)

    private_route_table_name = f"{project_name}-private-rt"
    candidates = [item for item in route_tables if _tag_map(item).get("Name") == private_route_table_name]
    if len(candidates) > 1:
        raise NetworkImportError(f"Mais de uma route table {private_route_table_name}; import ambíguo.")
    target = candidates[0] if candidates else None
    target_id = target.get("RouteTableId") if target else None
    if target:
        if target.get("VpcId") != vpc_id or target.get("OwnerId") != expected_account:
            raise NetworkImportError("Route table privada não pertence à VPC/conta esperada.")
        _add_import(imports, state_ids, addresses, ROUTE_TABLE_ADDRESS, target_id, target_id)

    for index, _, _ in PRIVATE_SUBNETS:
        subnet_id = subnet_ids.get(index)
        if not subnet_id:
            continue
        explicit = [
            (table, association)
            for table in route_tables
            for association in table.get("Associations", [])
            if association.get("SubnetId") == subnet_id and association.get("Main") is not True
        ]
        if any(table.get("RouteTableId") != target_id for table, _ in explicit):
            raise NetworkImportError(
                f"Subnet {subnet_id} está associada a outra route table; associação não será substituída automaticamente."
            )
        matching = [association for table, association in explicit if table.get("RouteTableId") == target_id]
        if len(matching) > 1:
            raise NetworkImportError(f"Associações duplicadas para subnet {subnet_id}; import ambíguo.")
        if matching:
            association_id = matching[0].get("RouteTableAssociationId")
            if not isinstance(association_id, str):
                raise NetworkImportError(f"Associação da subnet {subnet_id} sem ID válido.")
            address = f"aws_route_table_association.private_association[{index}]"
            _add_import(
                imports, state_ids, addresses, address, f"{subnet_id}/{target_id}", association_id
            )

    cluster_present = cluster_exists(cluster_name, region, run=run)
    if cluster_present:
        if "aws_eks_cluster.autoflow" not in addresses:
            raise NetworkImportError("Cluster EKS existente não está no State; import EKS exige reconciliação específica.")
        if state_ids.get("aws_eks_cluster.autoflow") != cluster_name:
            raise NetworkImportError("O endereço EKS no State não aponta ao cluster esperado.")
        nodegroups = run_json(
            aws + ["eks", "list-nodegroups", "--cluster-name", cluster_name, "--region", region], run
        ).get("nodegroups")
        if not isinstance(nodegroups, list):
            raise NetworkImportError("ListNodegroups retornou resposta incompleta.")
        if nodegroup_name in nodegroups:
            node_address = "aws_eks_node_group.node_group"
            expected_node_id = f"{cluster_name}:{nodegroup_name}"
            if node_address not in addresses or state_ids.get(node_address) != expected_node_id:
                raise NetworkImportError("Node group existente fora do State; reconciliação específica necessária.")
    return imports


def require_approval(imports: list[tuple[str, str]], approved: bool) -> None:
    if imports and not approved:
        raise NetworkImportError(
            "Recursos de rede do Autoflow existem sem endereço no Terraform State. "
            "Dispare workflow_dispatch com approve_eks_state_reconciliation=true após conferir o inventário."
        )


def render_imports(imports: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'import {{\n  to = {address}\n  id = "{resource_id}"\n}}'
        for address, resource_id in imports
    ) + ("\n" if imports else "")


def write_output(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise NetworkImportError(f"Arquivo de imports já existe com conteúdo diferente: {path}.")
        return
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--allow-reconciliation", choices=("true", "false"), default="false")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        addresses = state_addresses()
        state_ids = state_resource_ids(addresses)
        imports = discover_imports(
            args.expected_account, args.region, addresses, state_ids, project_name=args.project_name
        )
        require_approval(imports, args.allow_reconciliation == "true")
        write_output(args.output, render_imports(imports))
    except (NetworkImportError, RuntimeError, OSError) as error:
        print(f"Reconciliação automática da rede EKS bloqueada: {error}", file=sys.stderr)
        return 1
    print(f"Imports de rede autorizados e inequívocos preparados: {len(imports)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
