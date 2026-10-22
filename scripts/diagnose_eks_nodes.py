#!/usr/bin/env python3
"""Compara instâncias running do managed node group com nós Kubernetes Ready."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


class DiagnosticError(Exception):
    """Erro ao coletar estado AWS/Kubernetes."""


def run_json(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise DiagnosticError(f"Comando necessário não encontrado: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        # Evita imprimir stderr de comandos que possam conter dados do ambiente.
        raise DiagnosticError(f"Falha no comando de leitura: {' '.join(command[:3])}") from error
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DiagnosticError(f"Resposta JSON inválida de {command[0]}") from error


def compare_instances(
    running_instance_ids: set[str], nodes: list[dict[str, Any]], desired_size: int | None = None
) -> dict[str, Any]:
    registered: dict[str, bool] = {}
    for node in nodes:
        provider_id = node.get("spec", {}).get("providerID", "")
        instance_id = provider_id.rsplit("/", 1)[-1] if provider_id else ""
        if not instance_id.startswith("i-"):
            continue
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in node.get("status", {}).get("conditions", [])
        )
        registered[instance_id] = ready

    running_and_registered = running_instance_ids & registered.keys()
    return {
        "running": sorted(running_instance_ids),
        "ready": sorted(instance_id for instance_id in running_and_registered if registered[instance_id]),
        "not_ready": sorted(instance_id for instance_id in running_and_registered if not registered[instance_id]),
        "not_registered": sorted(running_instance_ids - registered.keys()),
        "ready_not_running": sorted(instance_id for instance_id, ready in registered.items() if ready and instance_id not in running_instance_ids),
        "desired_size": desired_size,
        "desired_mismatch": desired_size is not None and len(running_instance_ids) != desired_size,
    }


def diagnose(cluster: str, nodegroup: str, region: str) -> dict[str, Any]:
    nodegroup_data = run_json([
        "aws", "eks", "describe-nodegroup", "--cluster-name", cluster,
        "--nodegroup-name", nodegroup, "--region", region, "--output", "json",
    ]).get("nodegroup", {})
    asg_names = [item["name"] for item in nodegroup_data.get("resources", {}).get("autoScalingGroups", [])]
    if not asg_names:
        raise DiagnosticError("O managed node group não retornou Auto Scaling Group associado.")

    asg_data = run_json([
        "aws", "autoscaling", "describe-auto-scaling-groups",
        "--auto-scaling-group-names", *asg_names, "--region", region, "--output", "json",
    ])
    instance_ids = sorted({
        instance["InstanceId"]
        for group in asg_data.get("AutoScalingGroups", [])
        for instance in group.get("Instances", [])
        if instance.get("InstanceId")
    })
    if instance_ids:
        ec2_data = run_json([
            "aws", "ec2", "describe-instances", "--instance-ids", *instance_ids,
            "--region", region, "--output", "json",
        ])
        running_ids = {
            instance["InstanceId"]
            for reservation in ec2_data.get("Reservations", [])
            for instance in reservation.get("Instances", [])
            if instance.get("State", {}).get("Name") == "running"
        }
    else:
        running_ids = set()
    node_data = run_json(["kubectl", "get", "nodes", "-o", "json"])
    return {
        "nodegroup_status": nodegroup_data.get("status", "unknown"),
        "comparison": compare_instances(
            running_ids,
            node_data.get("items", []),
            nodegroup_data.get("scalingConfig", {}).get("desiredSize"),
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", default="eks-autoflow")
    parser.add_argument("--nodegroup", default="nodeg-autoflow")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    try:
        report = diagnose(args.cluster, args.nodegroup, args.region)
    except DiagnosticError as error:
        print(f"Diagnóstico não concluído: {error}", file=sys.stderr)
        return 1

    comparison = report["comparison"]
    print(f"Node Group status: {report['nodegroup_status']}")
    print(f"EC2 running no ASG: {len(comparison['running'])}")
    print(f"Nós Kubernetes Ready correspondentes: {len(comparison['ready'])}")
    if comparison["desired_mismatch"]:
        print(f"Discrepância de desired capacity: esperado {comparison['desired_size']}, running {len(comparison['running'])}")
    for key, label in (
        ("not_registered", "EC2 running sem Node registrado"),
        ("not_ready", "Node registrado não Ready"),
        ("ready_not_running", "Node Ready sem EC2 running correspondente"),
    ):
        values = comparison[key]
        print(f"{label}: {', '.join(values) if values else 'nenhum'}")
    return 2 if (
        comparison["desired_mismatch"]
        or comparison["not_registered"]
        or comparison["not_ready"]
        or comparison["ready_not_running"]
    ) else 0


if __name__ == "__main__":
    sys.exit(main())
