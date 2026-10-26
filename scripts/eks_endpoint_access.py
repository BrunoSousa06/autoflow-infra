"""Gerencia o CIDR temporário do runner no endpoint público do EKS."""

import argparse
import ipaddress
import json
import os
import re
import tempfile
import subprocess
import sys
import time


PERMANENT_CIDR = "189.6.8.245/32"


class LeaseReadError(RuntimeError):
    """Falha classificada ao ler o lease no S3, sem propagar saída bruta do AWS CLI."""

    def __init__(self, category, *, operation=None, bucket=None, key=None, returncode=None):
        self.category = category
        self.operation = operation
        self.bucket = bucket
        self.key = key
        self.returncode = returncode
        message = f"Falha ao ler lease do S3: {category}"
        if operation is not None:
            diagnostic = json.dumps({
                "operation": operation,
                "bucket": bucket,
                "key": key,
                "exit_code": returncode,
                "category": category,
            }, ensure_ascii=True, separators=(",", ":"))
            message += f"; diagnóstico={diagnostic}"
        super().__init__(message)


class AwsCli:
    def __call__(self, *args):
        result = subprocess.run(["aws", *args, "--output", "json"], check=True, capture_output=True, text=True)
        return json.loads(result.stdout or "{}")


def cluster_config(aws, cluster, region):
    try:
        return aws("eks", "describe-cluster", "--name", cluster, "--region", region)["cluster"]["resourcesVpcConfig"]
    except subprocess.CalledProcessError as error:
        # A first-time provision has no cluster yet. Only the explicit EKS
        # not-found response is benign; expired credentials and AccessDenied
        # must remain fatal.
        message = (error.stderr or "").lower()
        if "resourcenotfoundexception" in message or "resource not found" in message:
            return None
        raise


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
    if config is None:
        return None
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
    lease = validate_lease(lease)
    config = cluster_config(aws, cluster, region)
    if config is None:
        # O cluster foi recriado/resetado; a allowlist e o lease antigo não se aplicam.
        remove_lease()
        return
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
        category = classify_lease_read_error(result.stderr)
        if category == "not_found":
            return None
        raise LeaseReadError(
            category,
            operation="aws s3 cp",
            bucket=bucket,
            key=key,
            returncode=result.returncode,
        )
    try:
        return validate_lease(json.loads(result.stdout))
    except (json.JSONDecodeError, TypeError) as error:
        raise LeaseReadError("invalid_lease") from error


def classify_lease_read_error(stderr):
    message = (stderr or "").lower()
    if "expiredtoken" in message:
        return "expired_token"
    if "accessdenied" in message or "(403)" in message:
        return "access_denied"
    if "nosuchbucket" in message:
        return "unexpected"
    if any(marker in message for marker in (
        "endpointconnectionerror", "could not connect", "connection timed out",
        "temporary failure in name resolution", "name or service not known", "ssl validation failed",
    )):
        return "connectivity"
    if re.search(r"\(nosuchkey\)", message) or re.search(
        r"\(404\) when calling the (?:headobject|getobject) operation\b", message
    ):
        return "not_found"
    return "unexpected"


def validate_lease(lease):
    if not isinstance(lease, dict):
        raise LeaseReadError("invalid_lease")
    temporary = lease.get("temporary_cidr")
    originals = lease.get("original_cidrs")
    if (not isinstance(temporary, str) or not isinstance(originals, list) or not originals
            or any(not isinstance(value, str) for value in originals)):
        raise LeaseReadError("invalid_lease")
    try:
        temporary_network = ipaddress.ip_network(temporary, strict=True)
        original_networks = [ipaddress.ip_network(value, strict=True) for value in originals]
    except (TypeError, ValueError) as error:
        raise LeaseReadError("invalid_lease") from error
    if temporary_network.version != 4 or temporary_network.prefixlen != 32:
        raise LeaseReadError("invalid_lease")
    if any(network.version != 4 or str(network) == "0.0.0.0/0" for network in original_networks):
        raise LeaseReadError("invalid_lease")
    normalized_originals = sorted({str(network) for network in original_networks})
    if PERMANENT_CIDR not in normalized_originals or str(temporary_network) in normalized_originals:
        raise LeaseReadError("invalid_lease")
    return {"temporary_cidr": str(temporary_network), "original_cidrs": normalized_originals}


def remove_lease():
    bucket, key = lease_location()
    subprocess.run(["aws", "s3", "rm", f"s3://{bucket}/{key}"], check=True, capture_output=True, text=True)


def reconcile(aws, cluster, region):
    return cleanup_if_lease_exists(aws, cluster, region)


def cleanup_if_lease_exists(aws, cluster, region):
    lease = load_lease()
    if lease is None:
        return False
    cleanup(aws, cluster, region, lease)
    return True


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
        if lease is None:
            print("Cluster EKS ausente; autorização temporária ignorada antes da criação.")
            return
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
                cleanup_if_lease_exists(aws, args.cluster, args.region)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise
