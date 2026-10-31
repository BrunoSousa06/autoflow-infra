"""Testes da classificação segura de ações do Terraform plan."""
import contextlib
import io
import unittest

from review_gateway_plan import review


def change(address, resource_type, after, actions=("create",), importing=None):
    value = {"actions": list(actions), "after": after}
    if importing is not None:
        value["importing"] = {"id": importing}
    return {"address": address, "type": resource_type, "change": value}


def initial_plan():
    changes = [
        change("module.private_eks.aws_lb.this", "aws_lb", {
            "internal": True, "load_balancer_type": "application",
        }),
        change("module.private_eks.aws_security_group.alb", "aws_security_group", {
            "ingress": [], "egress": [],
        }),
        change("module.private_eks.aws_security_group.link", "aws_security_group", {
            "ingress": [], "egress": [],
        }),
        change('module.private_eks.aws_lb_target_group.this["backend"]', "aws_lb_target_group", {
            "target_type": "instance", "port": 30081, "protocol": "HTTP",
        }),
        change('module.private_eks.aws_lb_target_group.this["frontend"]', "aws_lb_target_group", {
            "target_type": "instance", "port": 30080, "protocol": "HTTP",
        }),
        change("aws_apigatewayv2_integration.login", "aws_apigatewayv2_integration", {
            "integration_type": "AWS_PROXY", "payload_format_version": "2.0",
        }),
        change("aws_lambda_permission.login", "aws_lambda_permission", {
            "principal": "apigateway.amazonaws.com", "action": "lambda:InvokeFunction",
            "source_account": "123456789012", "source_arn": "arn:aws:execute-api:region:account:api/*",
        }),
        change("aws_apigatewayv2_stage.this", "aws_apigatewayv2_stage", {
            "access_log_settings": [{"format": '{"requestId":"$context.requestId","route":"$context.routeKey","status":"$context.status","latency":"$context.responseLatency","integrationStatus":"$context.integrationStatus"}'}],
        }),
        change("module.private_eks.aws_apigatewayv2_vpc_link.this", "aws_apigatewayv2_vpc_link", {}),
    ]
    return {"resource_changes": changes}


def import_change(actions=("no-op",), importing="cjhmlk"):
    return change(
        "module.private_eks.aws_apigatewayv2_vpc_link.this",
        "aws_apigatewayv2_vpc_link", {}, actions, importing,
    )


def security_group_import_change(actions=("no-op",), importing="sg-0123456789abcdef0", **overrides):
    after = {
        "name": "autoflow-homolog-link-21105a8963a9a1a77ea4d9dd4a",
        "description": "Saida do VPC Link exclusivamente para o ALB interno",
        "vpc_id": "vpc-0123456789abcdef0",
        "ingress": [],
        "egress": [],
        "tags_all": {"Project": "autoflow", "Environment": "homolog", "ManagedBy": "Terraform"},
    }
    after.update(overrides)
    return change(
        "module.private_eks.aws_security_group.link",
        "aws_security_group", after, actions, importing,
    )


def real_import_replace_plan():
    """Formato equivalente ao resource_changes emitido por terraform show -json."""
    plan = initial_plan()
    vpc_link = plan["resource_changes"][-1]
    vpc_link["change"].update({
        "actions": ["delete", "create"],
        "before": {
            "id": "a1b2c3d4e5",
            "name": "autoflow-homolog",
            "subnet_ids": ["subnet-0123456789abcdef0"],
            "security_group_ids": ["sg-0123456789abcdef0"],
        },
        "after": {
            "name": "autoflow-homolog",
            "subnet_ids": ["subnet-0123456789abcdef0"],
            "security_group_ids": ["sg-0123456789abcdef0"],
        },
        "replace_paths": [["security_group_ids"]],
        "importing": {"id": "a1b2c3d4e5"},
    })
    return plan


class ReviewGatewayPlanTest(unittest.TestCase):
    def test_accepts_criacao_inicial_sem_contagem_fixa(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            review(initial_plan(), "123456789012")
        self.assertIn("Plan aprovado", output.getvalue())

    def test_accepts_import_sem_alteracoes_com_id_real(self):
        plan = {"resource_changes": [import_change()]}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            review(plan, "123456789012")
        self.assertIn("imports declarativos=1", output.getvalue())

    def test_accepts_import_do_security_group_anexado_ao_vpc_link_sem_drift(self):
        plan = initial_plan()
        plan["resource_changes"].append(security_group_import_change())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            review(plan, "123456789012")
        self.assertIn("1 imports declarativos", output.getvalue())

    def test_rejects_import_do_security_group_se_exigir_update_ou_drift(self):
        for item in (
            security_group_import_change(actions=("update",)),
            security_group_import_change(egress=[{"cidr_ipv4": "0.0.0.0/0"}]),
            security_group_import_change(tags_all={"Project": "other"}),
        ):
            with self.subTest(item=item), self.assertRaises(RuntimeError):
                review({"resource_changes": [item]}, "123456789012")

    def test_accepts_import_com_substituicao_autorizada(self):
        plan = real_import_replace_plan()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            review(plan, "123456789012", allow_destructive=True)
        self.assertIn("1 imports declarativos", output.getvalue())

    def test_diagnoses_each_import_validation_condition_without_echoing_id(self):
        cases = (
            ("address fora", lambda item: item.update(address="aws_vpc.wrong")),
            ("type diferente", lambda item: item.update(type="aws_vpc")),
            ("actions não permitidas", lambda item: item["change"].update(actions=["update"])),
            ("importing.id ausente ou inválido", lambda item: item["change"].update(importing={"id": "id/com-separador"})),
        )
        for expected, mutate in cases:
            with self.subTest(expected=expected):
                item = import_change(actions=("delete", "create"), importing="a1b2c3d4e5")
                mutate(item)
                with self.assertRaisesRegex(RuntimeError, expected) as raised:
                    review({"resource_changes": [item]}, "123456789012", allow_destructive=True)
                self.assertIn("ALLOW_DESTRUCTIVE=true", str(raised.exception))
                self.assertNotIn("a1b2c3d4e5", str(raised.exception))

    def test_rejeita_import_com_substituicao_sem_autorizacao(self):
        plan = initial_plan()
        replacement = plan["resource_changes"][-1]
        replacement["change"]["actions"] = ["delete", "create"]
        replacement["change"]["importing"] = {"id": "cjhmlk"}
        with self.assertRaisesRegex(RuntimeError, "actions não permitidas"):
            review(plan, "123456789012", allow_destructive=False)

    def test_rejeita_import_fora_do_vpc_link_esperado(self):
        plan = {"resource_changes": [import_change()]}
        plan["resource_changes"][0]["address"] = "aws_vpc.other"
        with self.assertRaisesRegex(RuntimeError, "address fora"):
            review(plan, "123456789012", allow_destructive=True)

    def test_rejeita_id_de_import_invalido(self):
        with self.assertRaisesRegex(RuntimeError, "importing.id ausente ou inválido"):
            review({"resource_changes": [import_change(importing="vpclink/invalid")]}, "123456789012")

    def test_gateway_workflow_forwards_dispatch_authorization_to_reviewer(self):
        from pathlib import Path
        workflow = (Path(__file__).parents[1] / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        self.assertIn("ALLOW_DESTRUCTIVE: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_destructive && 'true' || 'false' }}", workflow)
        self.assertNotIn("github.event_name == 'push' && 'true'", workflow)
        self.assertIn('ALLOW_DESTRUCTIVE="$ALLOW_DESTRUCTIVE" python ../../scripts/review_gateway_plan.py gateway.tfplan', workflow)

    def test_rejeita_substituicao_nao_autorizada(self):
        plan = initial_plan()
        plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]
        with self.assertRaisesRegex(RuntimeError, "operações fora do escopo"):
            review(plan, "123456789012", allow_destructive=False)

    def test_rejeita_exclusao_nao_autorizada(self):
        plan = initial_plan()
        plan["resource_changes"][0]["change"]["actions"] = ["delete"]
        with self.assertRaisesRegex(RuntimeError, "operações fora do escopo"):
            review(plan, "123456789012", allow_destructive=False)

    def test_rejeita_plan_invalido(self):
        for invalid_plan in (None, {}, {"resource_changes": None},
                             {"resource_changes": [{"address": "aws_vpc.x", "change": {}}]}):
            with self.subTest(plan=invalid_plan):
                with self.assertRaisesRegex(RuntimeError, "inválido ou incompleto"):
                    review(invalid_plan, "123456789012")


if __name__ == "__main__":
    unittest.main()
