"""Bootstrap explícito e idempotente do bucket de Terraform State."""

import argparse
import os
import re
import subprocess
import sys

from resolve_state_bucket import resolve_state_bucket


def run(*args):
    return subprocess.run(["aws", *args], check=True, capture_output=True, text=True)


def bootstrap(bucket, region, expected_owner, approve_create):
    if not region or not expected_owner or not expected_owner.isdigit() or len(expected_owner) != 12:
        raise ValueError("Bucket, região e AWS_EXPECTED_ACCOUNT_ID válidos são obrigatórios.")
    bucket = resolve_state_bucket(bucket, expected_owner, region)
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
    # Existing buckets are read-only: do not silently alter their controls.
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
    else:
        actual = (
            run("s3api", "get-public-access-block", "--bucket", bucket, "--expected-bucket-owner", expected_owner, "--region", region).stdout,
            run("s3api", "get-bucket-versioning", "--bucket", bucket, "--expected-bucket-owner", expected_owner, "--region", region).stdout,
            run("s3api", "get-bucket-encryption", "--bucket", bucket, "--expected-bucket-owner", expected_owner, "--region", region).stdout,
        )
        required = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets", "Enabled", "AES256")
        if not all(value in " ".join(actual) for value in required):
            raise RuntimeError("Bucket existente não atende aos controles exigidos; nenhuma configuração foi alterada.")
    # Never write/copy/delete Terraform state objects.
    run("s3api", "head-bucket", "--bucket", bucket, "--expected-bucket-owner", expected_owner, "--region", region)


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
