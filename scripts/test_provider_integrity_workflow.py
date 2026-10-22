from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pipeline.yml"


class ProviderIntegrityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.plan = cls.workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        cls.apply = cls.workflow.split("\n  apply:\n", 1)[1]

    def test_plan_and_apply_discard_only_cached_provider_plugins_before_init(self):
        for job in (self.plan, self.apply):
            with self.subTest(job="plan" if job is self.plan else "apply"):
                init_step = job.split("- name: Inicializar Terraform", 1)[1].split("- name:", 1)[0]
                cleanup_position = init_step.index("rm -rf .terraform/providers")
                init_position = init_step.index("terraform init")

                self.assertLess(cleanup_position, init_position)
                self.assertIn("terraform init -input=false -lockfile=readonly", init_step)
                self.assertNotIn("rm -rf .terraform\n", init_step)
                self.assertNotIn("terraform init -upgrade", init_step)

    def test_plan_and_apply_use_the_same_committed_lockfile_without_provider_artifact_or_cache(self):
        plan_checkout = self.plan.split("- uses: actions/checkout@v4", 1)[1].split("- name:", 1)[0]
        apply_checkout = self.apply.split("- uses: actions/checkout@v4", 1)[1].split("- name:", 1)[0]
        upload = self.plan.split("- name: Publicar artifact criptografado da execução", 1)[1]

        self.assertIn("ref: ${{ github.sha }}", plan_checkout)
        self.assertIn("ref: ${{ github.sha }}", apply_checkout)
        self.assertIn("infra/infra.tfplan.gpg", upload)
        self.assertNotIn("infra/.terraform", upload)
        self.assertNotIn("actions/cache", self.workflow)
        self.assertNotIn("TF_PLUGIN_CACHE_DIR", self.workflow)

    def test_provider_lockfile_keeps_approved_versions_and_checksums(self):
        lockfile = (ROOT / "infra/.terraform.lock.hcl").read_text(encoding="utf-8")

        for provider, version in (
            ("hashicorp/aws", "5.100.0"),
            ("hashicorp/helm", "3.3.0"),
            ("newrelic/newrelic", "3.100.5"),
        ):
            with self.subTest(provider=provider):
                block = lockfile.split(f'provider "registry.terraform.io/{provider}"', 1)[1].split("\n}", 1)[0]
                self.assertIn(f'version     = "{version}"', block)
                self.assertIn('"h1:', block)
                self.assertIn('"zh:', block)


if __name__ == "__main__":
    unittest.main()
