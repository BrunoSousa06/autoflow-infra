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

    def test_accepts_import_com_substituicao_autorizada(self):
        plan = initial_plan()
        replacement = plan["resource_changes"][-1]
        replacement["change"]["actions"] = ["delete", "create"]
        replacement["change"]["importing"] = {"id": "cjhmlk"}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            review(plan, "123456789012", allow_destructive=True)
        self.assertIn("1 imports declarativos", output.getvalue())

    def test_rejeita_import_com_substituicao_sem_autorizacao(self):
        plan = initial_plan()
        replacement = plan["resource_changes"][-1]
        replacement["change"]["actions"] = ["delete", "create"]
        replacement["change"]["importing"] = {"id": "cjhmlk"}
        with self.assertRaisesRegex(RuntimeError, "import fora do VPC Link esperado"):
            review(plan, "123456789012", allow_destructive=False)

    def test_rejeita_import_fora_do_vpc_link_esperado(self):
        plan = {"resource_changes": [import_change()]}
        plan["resource_changes"][0]["address"] = "aws_vpc.other"
        with self.assertRaisesRegex(RuntimeError, "import fora do VPC Link esperado"):
            review(plan, "123456789012", allow_destructive=True)

    def test_rejeita_id_de_import_invalido(self):
        with self.assertRaisesRegex(RuntimeError, "import fora do VPC Link esperado"):
            review({"resource_changes": [import_change(importing="vpclink/invalid")]}, "123456789012")

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
