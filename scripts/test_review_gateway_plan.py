"""Testes da classificação segura de ações do Terraform plan."""
import contextlib
import io
import unittest

from review_gateway_plan import review


def plan_with_action(actions):
    return {
        "format_version": "1.2",
        "terraform_version": "1.16.5",
        "planned_values": {"root_module": {"resources": [{"address": "aws_vpc.existing"}]}},
        "prior_state": {"values": {"root_module": {"resources": [{"address": "aws_vpc.existing"}]}}},
        "resource_changes": [{
            "address": "aws_vpc.existing",
            "change": {"actions": actions},
        }],
    }


class ReviewGatewayPlanTest(unittest.TestCase):
    def test_accepts_declarative_import_of_existing_vpc_link(self):
        plan = plan_with_action(["no-op"])
        change = plan["resource_changes"][0]
        change["address"] = 'module.private_eks.aws_apigatewayv2_vpc_link.this'
        change["type"] = "aws_apigatewayv2_vpc_link"
        change["change"]["importing"] = {"id": "vpclink-123456"}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            review(plan, "123456789012")
        self.assertIn("imports declarativos=1", output.getvalue())

    def test_rejects_import_outside_vpc_link_scope(self):
        plan = plan_with_action(["no-op"])
        plan["resource_changes"][0]["change"]["importing"] = {"id": "resource-id"}
        with self.assertRaisesRegex(RuntimeError, "import fora do VPC Link esperado"):
            review(plan, "123456789012")

    def test_plan_sem_alteracoes_aprovado_sem_contar_state_como_criacao(self):
        plan = plan_with_action(["no-op"])
        # Inventário do state e valores planejados não são mudanças deste plan.
        plan["resource_changes"] = []
        with contextlib.redirect_stdout(io.StringIO()) as output:
            review(plan, "123456789012")
        self.assertIn("Ações planejadas: {}", output.getvalue())
        self.assertIn("sem alterações AWS", output.getvalue())

    def test_criacao_inesperada_reprovada(self):
        with self.assertRaisesRegex(RuntimeError, "escopo autorizado"):
            review(plan_with_action(["create"]), "123456789012")

    def test_destruicao_nao_autorizada_reprovada(self):
        with self.assertRaisesRegex(RuntimeError, "escopo autorizado"):
            review(plan_with_action(["delete"]), "123456789012")

    def test_destruicao_autorizada_passou_do_guard_de_acoes(self):
        with self.assertRaisesRegex(RuntimeError, "152 criações"):
            review(plan_with_action(["delete"]), "123456789012", allow_destructive=True)

    def test_substituicao_nao_autorizada_reprovada(self):
        with self.assertRaisesRegex(RuntimeError, "escopo autorizado"):
            review(plan_with_action(["delete", "create"]), "123456789012")

    def test_substituicao_autorizada_passou_do_guard_de_acoes(self):
        with self.assertRaisesRegex(RuntimeError, "152 criações"):
            review(plan_with_action(["delete", "create"]), "123456789012", allow_destructive=True)

    def test_json_invalido_ou_incompleto_reprovado(self):
        for invalid_plan in (None, {}, {"resource_changes": None},
                             {"resource_changes": [{"address": "aws_vpc.x", "change": {}}]}):
            with self.subTest(plan=invalid_plan):
                with self.assertRaisesRegex(RuntimeError, "inválido ou incompleto"):
                    review(invalid_plan, "123456789012")


if __name__ == "__main__":
    unittest.main()
