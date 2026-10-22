"""Bloqueia exclusões e substituições no plan de VPC/EKS sem autorização."""

import argparse
import json
import sys
from pathlib import Path


class PlanReviewError(RuntimeError):
    """O plan é inválido ou contém uma ação destrutiva não autorizada."""


def review_plan(plan, allow_destructive=False):
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise PlanReviewError("JSON do plan sem resource_changes válido.")

    destructive = []
    counts = {}
    for item in changes:
        if not isinstance(item, dict) or not isinstance(item.get("change"), dict):
            raise PlanReviewError("Entrada inválida em resource_changes.")
        address = item.get("address")
        actions = item["change"].get("actions")
        if (not isinstance(address, str) or not isinstance(actions, list)
                or not all(isinstance(action, str) for action in actions)):
            raise PlanReviewError("Endereço ou ações inválidos em resource_changes.")
        label = ",".join(actions)
        counts[label] = counts.get(label, 0) + 1
        if "delete" in actions:
            destructive.append(address)

    if destructive and not allow_destructive:
        raise PlanReviewError(
            "Exclusões/substituições bloqueadas sem autorização explícita: "
            + ", ".join(sorted(destructive))
        )
    return counts, sorted(destructive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_json", type=Path)
    parser.add_argument("--allow-destructive", choices=("true", "false"), default="false")
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise PlanReviewError("JSON do plan inválido.")
        counts, destructive = review_plan(plan, args.allow_destructive == "true")
    except (OSError, json.JSONDecodeError, PlanReviewError) as error:
        print(f"Revisão do plan bloqueada: {error}", file=sys.stderr)
        return 2

    print("Ações do Terraform Plan:", json.dumps(counts, sort_keys=True))
    if destructive:
        print("Exclusões/substituições autorizadas:", ", ".join(destructive))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
