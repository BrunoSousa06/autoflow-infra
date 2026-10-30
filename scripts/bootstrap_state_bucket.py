"""Bootstrap explícito e idempotente do bucket de Terraform State."""

import argparse
import json
import os
import re
import subprocess
import sys

from verify_aws_account import validate_account


def run(*args):
    return subprocess.run(["aws", *args], check=True, capture_output=True, text=True)


def bootstrap(bucket, region, expected_owner, approve_create):
    if not bucket or not bucket.strip() or not region or not expected_owner:
        raise ValueError("AWS_TERRAFORM_STATE_BUCKET, AWS_REGION e AWS_EXPECTED_ACCOUNT_ID são obrigatórios.")
    bucket = bucket.strip()
    identity = run("sts", "get-caller-identity", "--query", "Account", "--output", "text")
    validate_account(expected_owner, identity.stdout.strip())

    created = False
    try:
        run("s3api", "head-bucket", "--bucket", bucket, "--expected-bucket-owner", expected_owner, "--region", region)
    except subprocess.CalledProcessError as error:
        # AWS CLI returns 404 only for a genuinely absent bucket. AccessDenied,
        # wrong owner, network and all ambiguous errors fail closed.
        text = (error.stderr or "").lower()
        if "404" not in text and "nosuchbucket" not in text:
            raise
        if not approve_create:
            raise RuntimeError("Bucket ausente; criação requer aprovação explícita.")
        args = ["s3api", "create-bucket", "--bucket", bucket, "--region", region]
        if region != "us-east-1":
            args += ["--create-bucket-configuration", f"LocationConstraint={region}"]
        run(*args)
        created = True

    # Buckets preexistentes são somente leitura; apenas o recém-criado recebe configuração.
    settings = (
        ("s3api", "put-public-access-block", "--bucket", bucket, "--expected-bucket-owner", expected_owner,
         "--public-access-block-configuration", "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true", "--region", region),
        ("s3api", "put-bucket-versioning", "--bucket", bucket, "--expected-bucket-owner", expected_owner,
         "--versioning-configuration", "Status=Enabled", "--region", region),
        ("s3api", "put-bucket-encryption", "--bucket", bucket, "--expected-bucket-owner", expected_owner,
         "--server-side-encryption-configuration", '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}', "--region", region),
    )
    if created:
        for args in settings:
            run(*args)

    controls = _read_bucket_controls(bucket, region, expected_owner)
    if not _has_required_controls(*controls):
        raise RuntimeError("Bucket existente não atende aos controles exigidos; nenhuma configuração foi alterada.")

    # Never write/copy/delete Terraform state objects.
    run("s3api", "head-bucket", "--bucket", bucket, "--expected-bucket-owner", expected_owner, "--region", region)


def _read_bucket_controls(bucket, region, expected_owner):
    common = ("--bucket", bucket, "--expected-bucket-owner", expected_owner, "--region", region)
    return (
        json.loads(run("s3api", "get-public-access-block", *common).stdout),
        json.loads(run("s3api", "get-bucket-versioning", *common).stdout),
        json.loads(run("s3api", "get-bucket-encryption", *common).stdout),
    )


def _has_required_controls(public_access, versioning, encryption):
    if not all(isinstance(value, dict) for value in (public_access, versioning, encryption)):
        return False
    public_block = public_access.get("PublicAccessBlockConfiguration", {})
    if not isinstance(public_block, dict):
        return False
    required_public_controls = (
        "BlockPublicAcls",
        "IgnorePublicAcls",
        "BlockPublicPolicy",
        "RestrictPublicBuckets",
    )
    if not all(public_block.get(name) is True for name in required_public_controls):
        return False
    if versioning.get("Status") != "Enabled":
        return False

    encryption_config = encryption.get("ServerSideEncryptionConfiguration", {})
    if not isinstance(encryption_config, dict):
        return False
    encryption_rules = encryption_config.get("Rules", [])
    if not isinstance(encryption_rules, list) or len(encryption_rules) != 1:
        return False
    if not isinstance(encryption_rules[0], dict) or encryption_rules[0].get("Filter"):
        return False
    encryption_default = encryption_rules[0].get("ApplyServerSideEncryptionByDefault", {})
    if not isinstance(encryption_default, dict):
        return False
    return encryption_default.get("SSEAlgorithm") == "AES256" and not encryption_default.get("SSEKMSKeyId")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-create", action="store_true")
    args = parser.parse_args()
    try:
        bootstrap(os.environ.get("AWS_TERRAFORM_STATE_BUCKET"), os.environ.get("AWS_REGION"),
                  os.environ.get("AWS_EXPECTED_ACCOUNT_ID"), args.approve_create)
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or "")
        match = re.search(r"\(([^)]+)\) when calling", stderr)
        code = match.group(1) if match else "erro AWS não classificado"
        print(f"Bootstrap do bucket falhou: AWS retornou {code}.", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as error:
        print(f"Bootstrap do bucket falhou: {error}", file=sys.stderr)
        return 1
    print("Bucket de Terraform State verificado e protegido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
