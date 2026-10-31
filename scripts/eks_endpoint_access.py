"""Gerencia o CIDR temporário do runner no endpoint público do EKS."""

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PERMANENT_CIDR = "189.6.8.245/32"
UPDATE_RETRIES = 3
UPDATE_WAIT_ATTEMPTS = 60
UPDATE_WAIT_SECONDS = 10
NEWRELIC_LEASE_NAME_PREFIX = "eks-endpoint-lease-newrelic-"
LEGACY_NEWRELIC_LEASE_PREFIX = f"ci/{NEWRELIC_LEASE_NAME_PREFIX}"
NEWRELIC_LEASE_KEY = re.compile(
    r"^ci/(?:(?P<environment>homolog|production)/)?eks-endpoint-lease-newrelic-"
    r"(?P<run_id>[0-9]+)-(?P<attempt>[1-9][0-9]*)-(?P<job>plan|apply)\.json$"
)


class AwsOperationError(RuntimeError):
    def __init__(self, operation, error):
        stderr = error.stderr or ""
        match = re.search(r"An error occurred \(([^)]+)\) when calling ([^:]+)", stderr)
        self.code = match.group(1) if match else "UnknownAWSException"
        self.operation = operation
        super().__init__(
            f"Falha AWS em {operation}: {self.code}; exit code {error.returncode}."
        )


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
        try:
            result = subprocess.run(
                ["aws", *args, "--output", "json"], check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as error:
            raise AwsOperationError(" ".join(args[:2]), error) from error
        return json.loads(result.stdout or "{}")


def cluster_config(aws, cluster, region):
    try:
        return aws("eks", "describe-cluster", "--name", cluster, "--region", region)["cluster"]["resourcesVpcConfig"]
    except (AwsOperationError, subprocess.CalledProcessError) as error:
        # A first-time provision has no cluster yet. Only the explicit EKS
        # not-found response is benign; expired credentials and AccessDenied
        # must remain fatal.
        message = (error.stderr or "").lower() if isinstance(error, subprocess.CalledProcessError) else ""
        if isinstance(error, AwsOperationError) and error.code == "ResourceNotFoundException":
            return None
        if "resourcenotfoundexception" in message or "resource not found" in message:
            return None
        raise


def _wait_for_update(aws, cluster, region, update_id):
    for _ in range(UPDATE_WAIT_ATTEMPTS):
        update = aws(
            "eks", "describe-update", "--name", cluster, "--region", region, "--update-id", update_id
        )["update"]
        if update["status"] == "Successful":
            return
        if update["status"] in {"Failed", "Cancelled"}:
            raise RuntimeError(f"Atualização de endpoint EKS terminou como {update['status']}")
        time.sleep(UPDATE_WAIT_SECONDS)
    raise RuntimeError("Tempo limite aguardando atualização de endpoint EKS; lease mantido.")


def _wait_for_active_updates(aws, cluster, region):
    for _ in range(UPDATE_WAIT_ATTEMPTS):
        updates = aws("eks", "list-updates", "--name", cluster, "--region", region).get("updateIds", [])
        active = []
        for update_id in updates:
            update = aws(
                "eks", "describe-update", "--name", cluster, "--region", region, "--update-id", update_id
            )["update"]
            if update["status"] == "InProgress":
                active.append(update_id)
        if not active:
            return
        for update_id in active:
            _wait_for_update(aws, cluster, region, update_id)
    raise RuntimeError("Tempo limite aguardando atualizações EKS existentes; lease mantido.")


def update_and_wait(aws, cluster, region, cidrs):
    cidrs = set(cidrs)
    if "0.0.0.0/0" in cidrs:
        raise RuntimeError("CIDR público irrestrito não permitido")
    value = "publicAccessCidrs=" + ",".join(sorted(cidrs))
    for attempt in range(UPDATE_RETRIES):
        _wait_for_active_updates(aws, cluster, region)
        try:
            result = aws(
                "eks", "update-cluster-config", "--name", cluster, "--region", region,
                "--resources-vpc-config", value,
            )
        except AwsOperationError as error:
            if error.code != "ResourceInUseException" or attempt == UPDATE_RETRIES - 1:
                raise
            time.sleep(UPDATE_WAIT_SECONDS)
            continue
        _wait_for_update(aws, cluster, region, result["update"]["id"])
        return
    raise RuntimeError("Conflito transitório de atualização EKS; lease mantido.")


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
    return _cleanup(aws, cluster, region, lease)


def _cleanup(aws, cluster, region, lease, lease_key=None):
    lease = validate_lease(lease)
    config = cluster_config(aws, cluster, region)
    if config is None:
        # O cluster foi recriado/resetado; a allowlist e o lease antigo não se aplicam.
        if lease_key is None:
            remove_lease()
        else:
            remove_lease(lease_key)
        return
    current = set(config["publicAccessCidrs"])
    target = (current - {lease["temporary_cidr"]}) | set(lease["original_cidrs"])
    if "0.0.0.0/0" in target:
        raise RuntimeError("CIDR público irrestrito não permitido; lease mantido.")
    if target != current:
        update_and_wait(aws, cluster, region, target)
        confirmed = cluster_config(aws, cluster, region)
        if confirmed is None or set(confirmed["publicAccessCidrs"]) != target:
            raise RuntimeError("CIDRs restaurados não confirmados no endpoint EKS; lease mantido.")
    if lease_key is None:
        remove_lease()
    else:
        remove_lease(lease_key)


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


def load_lease(key=None):
    bucket, configured_key = lease_location()
    key = key or configured_key
    if not bucket or not key:
        raise RuntimeError("EKS_LEASE_BUCKET e EKS_LEASE_KEY são obrigatórios para reconciliação")
    head = subprocess.run(
        ["aws", "s3api", "head-object", "--bucket", bucket, "--key", key, "--output", "json"],
        capture_output=True,
        text=True,
    )
    if head.returncode:
        category = classify_lease_read_error(head.stderr)
        if category == "not_found":
            return None
        raise LeaseReadError(
            category,
            operation="aws s3api head-object",
            bucket=bucket,
            key=key,
            returncode=head.returncode,
        )

    result = subprocess.run(["aws", "s3", "cp", f"s3://{bucket}/{key}", "-"], capture_output=True, text=True)
    if result.returncode:
        category = classify_lease_read_error(result.stderr)
        # A successful HeadObject already proved the object existed. Any later
        # failure to read it (including a concurrent deletion) is fail-closed.
        if category == "not_found":
            category = "unexpected"
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


def remove_lease(key=None):
    bucket, configured_key = lease_location()
    key = key or configured_key
    subprocess.run(["aws", "s3", "rm", f"s3://{bucket}/{key}"], check=True, capture_output=True, text=True)


def reconcile(aws, cluster, region):
    return cleanup_if_lease_exists(aws, cluster, region)


def cleanup_if_lease_exists(aws, cluster, region):
    lease = load_lease()
    if lease is None:
        return False
    cleanup(aws, cluster, region, lease)
    return True


def newrelic_workflow_runs(token, repository):
    if not token or not re.fullmatch(r"[^/]+/[^/]+", repository or ""):
        raise RuntimeError("Identidade GitHub para reconciliar leases incompleta; operação bloqueada.")
    runs = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repository}/actions/workflows/newrelic.yml/runs"
            f"?per_page=100&page={page}"
        )
        request = Request(
            url,
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeError(
                "Não foi possível consultar com segurança o histórico do workflow New Relic; leases mantidos."
            ) from error
        page_runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(page_runs, list):
            raise RuntimeError("Resposta inválida do histórico New Relic; leases mantidos.")
        runs.extend(page_runs)
        if len(page_runs) < 100:
            return runs
        page += 1


def reconcile_orphan_leases(aws, cluster, region, token, repository, current_run_id, current_attempt):
    if not isinstance(current_attempt, int) or isinstance(current_attempt, bool) or current_attempt <= 0:
        raise RuntimeError("Attempt atual do GitHub inválido; leases mantidos.")
    environment = os.environ.get("GITHUB_DEPLOYMENT_ENVIRONMENT")
    if environment not in {"homolog", "production"}:
        raise RuntimeError("Environment GitHub inválido; leases mantidos.")
    runs = newrelic_workflow_runs(token, repository)
    reconciled = 0
    for run in runs:
        if not isinstance(run, dict):
            continue
        run_id = run.get("id")
        attempts = run.get("run_attempt")
        if (not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0
                or not isinstance(attempts, int) or isinstance(attempts, bool) or attempts <= 0):
            raise RuntimeError("Ownership de run New Relic inválido; leases mantidos.")
        # O attempt corrente permanece protegido; attempts anteriores do mesmo run
        # terminaram antes que o GitHub pudesse iniciar o attempt atual.
        completed_attempts = attempts if run.get("status") == "completed" else attempts - 1
        if str(run_id) == str(current_run_id):
            completed_attempts = min(completed_attempts, max(0, current_attempt - 1))
        for attempt in range(1, completed_attempts + 1):
            for job in ("plan", "apply"):
                keys = [f"ci/{environment}/{NEWRELIC_LEASE_NAME_PREFIX}{run_id}-{attempt}-{job}.json"]
                if environment == "homolog":
                    keys.append(f"{LEGACY_NEWRELIC_LEASE_PREFIX}{run_id}-{attempt}-{job}.json")
                for key in keys:
                    if not NEWRELIC_LEASE_KEY.fullmatch(key):
                        raise RuntimeError("Chave de lease fora do padrão esperado; operação bloqueada.")
                    lease = load_lease(key)
                    if lease is None:
                        continue
                    _cleanup(aws, cluster, region, lease, lease_key=key)
                    reconciled += 1
    return reconciled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("authorize", "cleanup", "reconcile", "reconcile-orphans"))
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
        if args.action == "reconcile-orphans":
            reconciled = reconcile_orphan_leases(
                aws,
                args.cluster,
                args.region,
                os.environ.get("GH_TOKEN", ""),
                os.environ.get("GITHUB_REPOSITORY", ""),
                os.environ.get("GITHUB_RUN_ID", ""),
                int(os.environ.get("GITHUB_RUN_ATTEMPT", "0")),
            )
            print(f"Leases órfãos reconciliados: {reconciled}")
        elif args.action == "reconcile":
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
