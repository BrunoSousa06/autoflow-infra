"""Gerencia o CIDR temporário do runner no endpoint público do EKS."""

import argparse
import ipaddress
import json
import os
import tempfile
import subprocess
import sys
import time


class AwsCli:
    def __call__(self, *args):
        result = subprocess.run(["aws", *args, "--output", "json"], check=True, capture_output=True, text=True)
        return json.loads(result.stdout or "{}")


def cluster_config(aws, cluster, region):
    return aws("eks", "describe-cluster", "--name", cluster, "--region", region)["cluster"]["resourcesVpcConfig"]


def update_and_wait(aws, cluster, region, cidrs):
    result = aws("eks", "update-cluster-config", "--name", cluster, "--region", region,
                 "--resources-vpc-config", "publicAccessCidrs=" + ",".join(sorted(set(cidrs))))
    update_id = result["update"]["id"]
    while True:
        update = aws("eks", "describe-update", "--name", cluster, "--region", region, "--update-id", update_id)["update"]
        if update["status"] == "Successful":
            return
        if update["status"] in {"Failed", "Cancelled"}:
            raise RuntimeError(f"Atualização de endpoint EKS terminou como {update['status']}")
        time.sleep(10)


def authorize(aws, cluster, region, runner_ip, baseline):
    cidr = str(ipaddress.ip_network(runner_ip + "/32", strict=True))
    config = cluster_config(aws, cluster, region)
    existing = set(config["publicAccessCidrs"])
    original = set(baseline)
    if not original.issubset(existing):
        raise RuntimeError("CIDR permanente configurado não está presente no endpoint; operação bloqueada")
    if cidr in {"0.0.0.0/0"}:
        raise RuntimeError("CIDR público irrestrito não permitido")
    reconcile(aws, cluster, region)
    existing = set(cluster_config(aws, cluster, region)["publicAccessCidrs"])
    lease = {"temporary_cidr": cidr, "original_cidrs": sorted(existing)}
    save_lease(lease)
    if cidr not in existing:
        update_and_wait(aws, cluster, region, existing | {cidr})
    return lease


def cleanup(aws, cluster, region, lease):
    config = cluster_config(aws, cluster, region)
    current = set(config["publicAccessCidrs"])
    target = (current - {lease["temporary_cidr"]}) | set(lease["original_cidrs"])
    if target != current:
        update_and_wait(aws, cluster, region, target)
    remove_lease()


def lease_location():
    bucket = os.environ.get("EKS_LEASE_BUCKET")
    key = os.environ.get("EKS_LEASE_KEY")
    return bucket, key


def save_lease(lease):
    bucket, key = lease_location()
    if not bucket or not key:
        raise RuntimeError("EKS_LEASE_BUCKET e EKS_LEASE_KEY são obrigatórios para registrar leases")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as stream:
        json.dump(lease, stream)
        path = stream.name
    try:
        subprocess.run(["aws", "s3", "cp", path, f"s3://{bucket}/{key}"], check=True, capture_output=True, text=True)
    finally:
        os.unlink(path)


def load_lease():
    bucket, key = lease_location()
    if not bucket or not key:
        raise RuntimeError("EKS_LEASE_BUCKET e EKS_LEASE_KEY são obrigatórios para reconciliação")
    result = subprocess.run(["aws", "s3", "cp", f"s3://{bucket}/{key}", "-"], capture_output=True, text=True)
    if result.returncode:
        if "404" in result.stderr or "Not Found" in result.stderr or "NoSuchKey" in result.stderr:
            return None
        raise RuntimeError("Não foi possível ler o registro durável de lease EKS")
    return json.loads(result.stdout)


def remove_lease():
    bucket, key = lease_location()
    subprocess.run(["aws", "s3", "rm", f"s3://{bucket}/{key}"], check=True, capture_output=True, text=True)


def reconcile(aws, cluster, region):
    lease = load_lease()
    if lease:
        cleanup(aws, cluster, region, lease)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("authorize", "cleanup", "reconcile"))
    parser.add_argument("--cluster", default="eks-autoflow")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--ip")
    parser.add_argument("--lease", default="eks-endpoint-lease.json")
    parser.add_argument("--baseline", default="189.6.8.245/32")
    args = parser.parse_args()
    aws = AwsCli()
    if args.action == "authorize":
        lease = authorize(aws, args.cluster, args.region, args.ip, args.baseline.split(","))
        with open(args.lease, "w", encoding="utf-8") as stream:
            json.dump(lease, stream)
    else:
        if args.action == "reconcile":
            reconcile(aws, args.cluster, args.region)
        else:
            if os.path.exists(args.lease):
                with open(args.lease, encoding="utf-8") as stream:
                    cleanup(aws, args.cluster, args.region, json.load(stream))
            else:
                reconcile(aws, args.cluster, args.region)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise
