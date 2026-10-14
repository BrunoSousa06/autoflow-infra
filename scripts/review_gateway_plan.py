"""Confere escopo, rede privada e permissões do plan sem expor valores."""
import json
import os
import subprocess
import sys


ALLOWED_METHODS = {"GET", "POST", "PATCH", "DELETE"}


def review(plan, expected_account):
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        raise RuntimeError("JSON do plan inválido ou incompleto: resource_changes ausente ou inválido.")

    resource_changes = plan["resource_changes"]
    for item in resource_changes:
        if (not isinstance(item, dict) or not isinstance(item.get("address"), str)
                or not isinstance(item.get("change"), dict)
                or not isinstance(item["change"].get("actions"), list)
                or not item["change"]["actions"]
                or not all(isinstance(action, str) for action in item["change"]["actions"])):
            raise RuntimeError("JSON do plan inválido ou incompleto: resource_changes malformado.")

    # Apenas resource_changes descreve as ações deste plan. Recursos presentes em
    # prior_state/planned_values representam inventário, não criações pendentes.
    changes = [item for item in resource_changes
               if item["change"]["actions"] not in (["no-op"], ["read"])]
    counts = {}
    for item in changes:
        action = ",".join(item["change"]["actions"])
        counts[action] = counts.get(action, 0) + 1
    print("Ações planejadas:", json.dumps(counts, sort_keys=True))
    if not changes:
        print("Plan aprovado na revisão estática: nenhuma alteração planejada.")
        return
    if len(changes) != 152 or any(item["change"]["actions"] != ["create"] for item in changes):
        raise RuntimeError("O plan não corresponde ao escopo autorizado: 152 criações e nenhuma atualização/exclusão.")

    resources = {item["address"]: item["change"].get("after") or {} for item in changes}
    required = {
        "module.private_eks.aws_lb.this",
        "module.private_eks.aws_security_group.alb",
        "module.private_eks.aws_security_group.link",
        "module.private_eks.aws_lb_target_group.this[\"backend\"]",
        "module.private_eks.aws_lb_target_group.this[\"frontend\"]",
        "aws_apigatewayv2_integration.login",
        "aws_lambda_permission.login",
        "aws_apigatewayv2_stage.this",
    }
    if not required.issubset(resources):
        raise RuntimeError("O plan não contém todos os recursos críticos esperados.")

    alb = resources["module.private_eks.aws_lb.this"]
    if alb.get("internal") is not True or alb.get("load_balancer_type") != "application":
        raise RuntimeError("O balanceador planejado não é um ALB interno.")
    for address in ("module.private_eks.aws_security_group.alb", "module.private_eks.aws_security_group.link"):
        security_group = resources[address]
        if security_group.get("ingress") != [] or security_group.get("egress") != []:
            raise RuntimeError(f"Security group {address} mantém regras inline/default inesperadas.")

    for item in changes:
        address = item["address"]
        after = item["change"].get("after") or {}
        if item["type"] == "aws_vpc_security_group_ingress_rule":
            if after.get("cidr_ipv4") or after.get("cidr_ipv6") or after.get("prefix_list_id"):
                raise RuntimeError(f"Regra ingress ampla ou pública no plan: {address}")
            if (not after.get("referenced_security_group_id")
                    and not (item["change"].get("after_unknown") or {}).get("referenced_security_group_id")):
                raise RuntimeError(f"Regra ingress sem origem restrita por SG: {address}")
        if item["type"] == "aws_vpc_security_group_egress_rule":
            if after.get("cidr_ipv4") or after.get("cidr_ipv6") or after.get("prefix_list_id"):
                raise RuntimeError(f"Regra egress ampla ou pública no plan: {address}")
            if (not after.get("referenced_security_group_id")
                    and not (item["change"].get("after_unknown") or {}).get("referenced_security_group_id")):
                raise RuntimeError(f"Regra egress sem destino restrito por SG: {address}")
            ports = (after.get("from_port"), after.get("to_port"))
            expected_ports = {
                'module.private_eks.aws_vpc_security_group_egress_rule.link["backend"]': (8081, 8081),
                'module.private_eks.aws_vpc_security_group_egress_rule.link["frontend"]': (8080, 8080),
                'module.private_eks.aws_vpc_security_group_egress_rule.alb["backend"]': (30081, 30081),
                'module.private_eks.aws_vpc_security_group_egress_rule.alb["frontend"]': (30080, 30080),
            }
            if address not in expected_ports or ports != expected_ports[address]:
                raise RuntimeError(f"Egress fora das portas do fluxo aprovado: {address}")
        if item["type"] == "aws_lb" and (after.get("internal") is not True or after.get("load_balancer_type") != "application"):
            raise RuntimeError(f"Balanceador fora do escopo interno: {address}")
        if item["type"] == "aws_iam_role":
            raise RuntimeError("O escopo não autoriza criar roles IAM.")
        if item["type"] == "aws_apigatewayv2_route":
            route = after.get("route_key", "")
            if " " not in route:
                raise RuntimeError(f"Route key inválida: {route}")
            method, path = route.split(" ", 1)
            if method not in ALLOWED_METHODS or path == "$default":
                raise RuntimeError(f"Rota genérica não autorizada: {route}")
            if path.startswith("/api/") and path == "/api/{proxy+}":
                raise RuntimeError(f"Proxy de negócio genérico não autorizado: {route}")
        if item["type"] == "aws_apigatewayv2_api":
            cors = after.get("cors_configuration")
            if cors and "*" in (cors[0].get("allow_origins") or []):
                raise RuntimeError("CORS wildcard não autorizado.")

    for key, port in (("backend", 30081), ("frontend", 30080)):
        target = resources[f'module.private_eks.aws_lb_target_group.this["{key}"]']
        if target.get("target_type") != "instance" or target.get("port") != port or target.get("protocol") != "HTTP":
            raise RuntimeError(f"Target group {key} não corresponde ao NodePort aprovado.")

    login = resources["aws_apigatewayv2_integration.login"]
    if login.get("integration_type") != "AWS_PROXY" or login.get("payload_format_version") != "2.0":
        raise RuntimeError("Login não usa a integração Lambda nativa payload v2.")
    permission = resources["aws_lambda_permission.login"]
    if (permission.get("principal") != "apigateway.amazonaws.com"
            or permission.get("action") != "lambda:InvokeFunction"
            or permission.get("source_account") != expected_account
            or (not permission.get("source_arn")
                and not (next(item for item in changes if item["address"] == "aws_lambda_permission.login")["change"].get("after_unknown") or {}).get("source_arn"))):
        raise RuntimeError("Permissão Lambda ausente ou fora do escopo de conta/API.")

    stage = resources["aws_apigatewayv2_stage.this"]
    log_format = stage.get("access_log_settings", [{}])[0].get("format", "")
    try:
        log_fields = set(json.loads(log_format))
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Formato de access log inválido.") from error
    if log_fields != {"requestId", "route", "status", "latency", "integrationStatus"}:
        raise RuntimeError("Access logs contêm campos extras ou omitem campos sanitizados esperados.")
    if any(term in log_format.lower() for term in ("authorization", "token", "query", "path", "sourceip", "body")):
        raise RuntimeError("Access logs podem registrar dados pessoais, tokens ou query strings.")

    print("Plan aprovado na revisão estática: 152 criações; somente ALB interno, SGs restritos, VPC Link e rotas/integrations definidas.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.getenv("TF_VAR_expected_account_id"):
        raise SystemExit("Uso: definir TF_VAR_expected_account_id e executar review_gateway_plan.py <arquivo.tfplan>")
    result = subprocess.run(["terraform", "show", "-json", sys.argv[1]], capture_output=True, text=True, check=True)
    review(json.loads(result.stdout), os.environ["TF_VAR_expected_account_id"])
