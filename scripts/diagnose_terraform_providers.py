"""Registra evidências de instalação dos providers sem expor dados de execução."""

import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
CONFIG_PATH_VARIABLES = ("TF_PLUGIN_CACHE_DIR", "TF_DATA_DIR", "TF_CLI_CONFIG_FILE")
CONFIG_DIRECTIVES = (
    "provider_installation",
    "plugin_cache_dir",
    "filesystem_mirror",
    "network_mirror",
    "direct",
    "dev_overrides",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report_command(label: str, command: list[str], *, print_output: bool = False) -> int:
    result = subprocess.run(command, cwd=INFRA, capture_output=True, text=True, check=False)
    print(f"{label}: exit={result.returncode}")
    if print_output and result.stdout:
        print(result.stdout.rstrip())
    return result.returncode


def main() -> None:
    print(f"Plataforma: {platform.system().lower()}_{platform.machine().lower()}")
    terraform = shutil.which("terraform")
    print(f"Executável Terraform no PATH: {terraform or 'não encontrado'}")
    if terraform:
        executable = Path(terraform).resolve()
        print(f"Executável Terraform resolvido: {executable}")
        print(f"SHA-256 do executável Terraform: {sha256(executable)}")
        print(f"Permissões do executável Terraform: {oct(stat.S_IMODE(executable.stat().st_mode))}")

    report_command("terraform version", ["terraform", "version"], print_output=True)
    report_command("terraform providers", ["terraform", "providers"], print_output=True)

    lockfile = INFRA / ".terraform.lock.hcl"
    print(f"Lockfile: {lockfile}")
    print(f"SHA-256 do lockfile: {sha256(lockfile)}")

    for name in CONFIG_PATH_VARIABLES:
        value = os.environ.get(name)
        print(f"{name}: {value if value else '<não definida>'}")

    cli_config = Path(os.environ.get("TF_CLI_CONFIG_FILE", Path.home() / ".terraformrc"))
    print(f"Arquivo de configuração CLI: {cli_config} (existe={cli_config.is_file()})")
    if cli_config.is_file():
        print(f"SHA-256 da configuração CLI: {sha256(cli_config)}")
        content = cli_config.read_text(encoding="utf-8", errors="replace")
        directives = sorted({item for item in CONFIG_DIRECTIVES if re.search(rf"\b{item}\b", content)})
        print(f"Diretivas de instalação detectadas: {', '.join(directives) if directives else '<nenhuma detectada>'}")

    providers_dir = INFRA / ".terraform" / "providers"
    print(f"Diretório de providers: {providers_dir} (existe={providers_dir.exists()}, symlink={providers_dir.is_symlink()})")
    if providers_dir.exists():
        print(f"Permissões do diretório de providers: {oct(stat.S_IMODE(providers_dir.stat().st_mode))}")
    binaries = sorted(providers_dir.glob("**/terraform-provider-*")) if providers_dir.exists() else []
    if not binaries:
        print("Binários de providers instalados: <nenhum encontrado>")
    for binary in binaries:
        resolved = binary.resolve()
        print(
            f"Provider: {binary} | resolvido={resolved} | symlink={binary.is_symlink()} "
            f"| SHA-256={sha256(resolved)} | permissões={oct(stat.S_IMODE(resolved.stat().st_mode))}"
        )
        file_command = shutil.which("file")
        if file_command:
            result = subprocess.run([file_command, "-L", str(binary)], capture_output=True, text=True, check=False)
            print(f"Formato do binário: {result.stdout.strip() or 'indisponível'}")

    schema_status = report_command(
        "terraform providers schema -json (saída descartada)",
        ["terraform", "providers", "schema", "-json"],
    )
    print(f"Verificação de carregamento dos providers: {'OK' if schema_status == 0 else 'FALHOU'}")


if __name__ == "__main__":
    main()
