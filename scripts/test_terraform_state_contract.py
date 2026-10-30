import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from terraform_state_contract import ContractError, ROOTS, main, validate_contract


def sample_contract():
    environments = {}
    for environment in ("homolog", "production"):
        roots = {}
        for index, root in enumerate(sorted(ROOTS)):
            roots[root] = {
                "account_id": "1" * 12 if environment == "homolog" else "2" * 12,
                "bucket": f"autoflow-{environment}-state",
                "region": "us-east-1",
                "key": f"{environment}/externally-selected/{root}-{index}.tfstate",
            }
        references = {
            "rds": {"vpc_eks": "vpc_eks"},
            "lambda": {"vpc_eks": "vpc_eks", "rds": "rds"},
            "application": {"rds": "rds"},
            "api_gateway": {"vpc_eks": "vpc_eks"},
            "newrelic": {"vpc_eks": "vpc_eks"},
        }
        for consumer, producers in references.items():
            roots[consumer]["consumes"] = {
                producer: roots[producer]["key"] for producer in producers
            }
        environments[environment] = {"roots": roots}
    return {"environments": environments}


class TerraformStateContractTests(unittest.TestCase):
    def test_accepts_environment_keys_with_external_suffixes_and_matching_consumers(self):
        validate_contract(sample_contract())

    def test_rejects_absent_environment_or_root_configuration(self):
        contract = sample_contract()
        del contract["environments"]["production"]["roots"]["newrelic"]
        with self.assertRaises(ContractError):
            validate_contract(contract)

    def test_rejects_missing_keys_and_missing_consumed_keys(self):
        contract = sample_contract()
        contract["environments"]["homolog"]["roots"]["rds"]["key"] = ""
        with self.assertRaises(ContractError):
            validate_contract(contract)
        contract = sample_contract()
        del contract["environments"]["homolog"]["roots"]["lambda"]["consumes"]["rds"]
        with self.assertRaises(ContractError):
            validate_contract(contract)

    def test_rejects_wrong_prefix_and_cross_environment_reference(self):
        contract = sample_contract()
        contract["environments"]["homolog"]["roots"]["rds"]["key"] = "production/rds.tfstate"
        with self.assertRaises(ContractError):
            validate_contract(contract)

    def test_rejects_duplicate_root_keys(self):
        contract = sample_contract()
        roots = contract["environments"]["homolog"]["roots"]
        roots["lambda"]["key"] = roots["rds"]["key"]
        with self.assertRaises(ContractError):
            validate_contract(contract)

    def test_rejects_application_rds_reference_divergence_in_both_environments(self):
        for environment in ("homolog", "production"):
            with self.subTest(environment=environment):
                contract = sample_contract()
                contract["environments"][environment]["roots"]["application"]["consumes"]["rds"] = (
                    f"{environment}/another.tfstate"
                )
                with self.assertRaises(ContractError):
                    validate_contract(contract)

    def test_rejects_account_bucket_or_region_inconsistent_with_environment(self):
        for field, value in (("account_id", "invalid"), ("bucket", "other-state-bucket"), ("region", "not-a-region")):
            with self.subTest(field=field):
                contract = sample_contract()
                contract["environments"]["production"]["roots"]["application"][field] = value
                with self.assertRaises(ContractError):
                    validate_contract(contract)

    def test_rejects_a_key_from_the_other_environment(self):
        contract = sample_contract()
        contract["environments"]["production"]["roots"]["vpc_eks"]["key"] = contract["environments"]["homolog"]["roots"]["vpc_eks"]["key"]
        with self.assertRaises(ContractError):
            validate_contract(contract)

    def test_cli_accepts_external_contract_file_and_fails_closed_for_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "contract.json"
            config.write_text(json.dumps(sample_contract()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(config)]), 0)
            config.write_text("{}", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(config)]), 1)


if __name__ == "__main__":
    unittest.main()
