#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador interativo de Zabbix Proxy com SQLite3.

Compativel com Python 3.6+ (incluindo Oracle Linux 8).
Normaliza diretivas duplicadas, seleciona ConfigFrequency (6.0) ou
ProxyConfigFrequency (6.4+) e oferece --repair-config sem reinstalacao.
Inclui o Zabbix Proxy 8.0 LTS e bloqueia atualizacoes acidentais.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SUPPORTED_ZABBIX = ["6.0", "6.4", "7.0", "7.2", "7.4", "8.0"]


def run(cmd, check=True, capture_output=False):
    """Executa um comando e interrompe a instalacao se ele falhar."""
    if isinstance(cmd, (list, tuple)):
        display = " ".join(shlex.quote(str(part)) for part in cmd)
    else:
        display = str(cmd)
    print(f"\n>> Executando: {display}")
    result = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        universal_newlines=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.STDOUT if capture_output else None,
    )
    if check and result.returncode != 0:
        if capture_output and result.stdout:
            print(result.stdout)
        raise RuntimeError(f"Erro ao executar comando: {display}")
    if capture_output:
        return result.stdout.strip()
    return ""


def ensure_root():
    if os.geteuid() != 0:
        print("Este script precisa ser executado como root.")
        print("Use: sudo python3 install_zabbix_proxy.py")
        sys.exit(1)


def ask(prompt, default=None, allowed=None, required=True):
    while True:
        label = prompt + (f" [{default}]" if default is not None else "") + ": "
        value = input(label).strip()
        if not value and default is not None:
            value = default
        if required and not value:
            print("Campo obrigatorio.")
            continue
        if allowed and value not in allowed:
            print(f"Valor invalido. Opcoes permitidas: {', '.join(allowed)}")
            continue
        return value


def detect_os():
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        raise RuntimeError("Arquivo /etc/os-release nao encontrado.")
    data = {}
    for line in os_release.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')

    os_id = data.get("ID", "").lower()
    version_id = data.get("VERSION_ID", "").lower()
    pretty_name = data.get("PRETTY_NAME", os_id)

    if os_id in ["ubuntu", "debian"]:
        family = "debian"
        major = version_id
    elif os_id in ["rhel", "rocky", "almalinux", "centos", "ol", "oracle"]:
        family = "rhel"
        major = version_id.split(".")[0]
    else:
        raise RuntimeError(f"Sistema nao suportado automaticamente: {pretty_name}")
    return {
        "id": os_id,
        "version": version_id,
        "pretty_name": pretty_name,
        "family": family,
        "major": major,
    }


def command_exists(command):
    return shutil.which(command) is not None


def pkg_manager():
    if command_exists("dnf"):
        return "dnf"
    if command_exists("yum"):
        return "yum"
    raise RuntimeError("Nem dnf nem yum estao disponiveis neste sistema.")


def install_prereqs(os_info):
    if os_info["family"] == "debian":
        run(["apt-get", "update"])
        run(["apt-get", "install", "-y", "wget", "curl", "gnupg", "lsb-release"])
    else:
        run([pkg_manager(), "install", "-y", "wget", "curl"])


def get_zabbix_release_rpm_url(os_info, zabbix_version):
    """URL de repositorio para distros da familia RHEL.

    Zabbix 7.0 usa o layout /oracle/9/x86_64 para Oracle Linux 9.
    Zabbix 7.2/7.4/8.0 usa /release/<distro>/<versao>/noarch.
    Para 6.0/6.4 o pacote compativel de RHEL e usado como fallback.
    """
    major = os_info["major"]
    os_id = os_info["id"]
    rpm = f"zabbix-release-latest-{zabbix_version}.el{major}.noarch.rpm"

    if zabbix_version in ["7.2", "7.4", "8.0"]:
        if zabbix_version == "8.0" and os_id in ["ol", "oracle"]:
            # A release RPM de 8.0 para OL8/9 fica em release/rhel;
            # os pacotes para Oracle ficam em stable/oracle.
            distro = "rhel"
        elif os_id in ["ol", "oracle"]:
            distro = "oracle" if major != "10" else "rhel"
        elif os_id == "almalinux":
            distro = "alma"
        elif os_id == "rocky":
            distro = "rocky"
        elif os_id == "centos":
            distro = "centos"
        else:
            distro = "rhel"
        return (
            f"https://repo.zabbix.com/zabbix/{zabbix_version}/release/"
            f"{distro}/{major}/noarch/{rpm}"
        )

    if major == "10":
        return (
            f"https://repo.zabbix.com/zabbix/{zabbix_version}/rhel/10/x86_64/"
            f"zabbix-release-{zabbix_version}-6.el10.noarch.rpm"
        )

    # O repositorio Oracle separado esta disponivel no layout antigo do 7.0.
    if os_id in ["ol", "oracle"] and zabbix_version == "7.0":
        distro = "oracle"
    else:
        distro = "rhel"
    return (
        f"https://repo.zabbix.com/zabbix/{zabbix_version}/{distro}/{major}/x86_64/"
        f"{rpm}"
    )


def install_zabbix_repo(os_info, zabbix_version):
    if os_info["id"] in ["ubuntu", "debian"]:
        distro = os_info["id"]
        release_pkg = f"zabbix-release_latest+{distro}{os_info['version']}_all.deb"
        url = (
            f"https://repo.zabbix.com/zabbix/{zabbix_version}/{distro}/"
            f"pool/main/z/zabbix-release/{release_pkg}"
        )
        local_file = f"/tmp/{release_pkg}"
        run(["wget", "-O", local_file, url])
        run(["dpkg", "-i", local_file])
        run(["apt-get", "update"])
    elif os_info["family"] == "rhel":
        manager = pkg_manager()
        url = get_zabbix_release_rpm_url(os_info, zabbix_version)
        print(f"URL do repositorio Zabbix: {url}")
        # Falha claramente em caso de URL invalida, antes de alterar o repositorio.
        run(["curl", "-fIL", "--retry", "2", "--connect-timeout", "15", url])
        run([manager, "install", "-y", url])
        run([manager, "clean", "all"])
    else:
        raise RuntimeError(f"Sistema nao suportado: {os_info['pretty_name']}")


def install_proxy(os_info):
    if os_info["family"] == "debian":
        run(["apt-get", "install", "-y", "zabbix-proxy-sqlite3"])
    else:
        run([pkg_manager(), "install", "-y", "zabbix-proxy-sqlite3", "zabbix-selinux-policy"])


def backup_file(file_path):
    path = Path(file_path)
    if path.exists():
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = f"{file_path}.{suffix}.bak"
        shutil.copy2(file_path, backup)
        print(f"Backup criado: {backup}")


def deduplicate_config(content):
    """Remove duplicatas identicas sem alterar diretivas repetiveis validas.

    Em caso de valores conflitantes, interrompe para revisao manual.
    """
    unique = {}
    result = []
    # Include e LoadModule podem ocorrer mais de uma vez no Zabbix.
    repeatable = {"Include", "LoadModule"}
    for line in content.splitlines(keepends=True):
        match = re.match(r"^[ \t]*([A-Za-z][A-Za-z0-9_]*)[ \t]*=(.*)$", line)
        if match:
            key, value = match.group(1), match.group(2).strip()
            if key not in repeatable:
                if key in unique:
                    if unique[key] != value:
                        raise RuntimeError(
                            "Parametro duplicado com valores diferentes: {} "
                            "({!r} x {!r}). Revise o arquivo manualmente.".format(
                                key, unique[key], value
                            )
                        )
                    continue
                unique[key] = value
        result.append(line)
    return "".join(result)


def set_config_value(content, key, value):
    """Garante uma unica linha ativa e preserva comentarios do arquivo."""
    lines = content.splitlines(keepends=True)
    active_pattern = re.compile(r"^[ \t]*" + re.escape(key) + r"[ \t]*=")
    indices = [i for i, line in enumerate(lines) if active_pattern.match(line)]
    replacement = "{}={}\n".format(key, value)
    if indices:
        # Reescreve a primeira linha e remove as demais, se houver.
        for i in reversed(indices[1:]):
            del lines[i]
        lines[indices[0]] = replacement
        return "".join(lines)

    # Quando ha um bloco '### Option: KEY' sem linha ativa, acrescenta
    # a diretiva na secao correta, logo depois de '# Default:'.
    heading_pattern = re.compile(r"^[ \t]*#{2,}[ \t]*Option:[ \t]*" + re.escape(key) + r"[ \t]*$")
    for i, line in enumerate(lines):
        if heading_pattern.match(line.rstrip("\r\n")):
            for j in range(i + 1, len(lines)):
                if re.match(r"^[ \t]*#{2,}[ \t]*Option:", lines[j]):
                    break
                if re.match(r"^[ \t]*#[ \t]*Default:", lines[j]):
                    lines.insert(j + 1, replacement)
                    return "".join(lines)
            break
    return content.rstrip("\r\n") + "\n" + replacement


def remove_config_keys(content, keys):
    """Apaga apenas diretivas ativas; preserva a documentacao comentada."""
    lines = content.splitlines(keepends=True)
    patterns = [re.compile(r"^[ \t]*" + re.escape(key) + r"[ \t]*=") for key in keys]
    return "".join(line for line in lines if not any(p.match(line) for p in patterns))


def installed_proxy_version():
    """Descobre a versao real do binario, sem depender da escolha no menu."""
    output = run(["zabbix_proxy", "--version"], capture_output=True)
    match = re.search(r"\b(\d+\.\d+)\.\d+\b", output)
    if not match:
        raise RuntimeError("Nao foi possivel identificar a versao instalada do Zabbix Proxy.")
    return match.group(1)



def prevent_unintended_upgrade(target_version):
    """Nao altera um Proxy de outra versao nem seu banco SQLite existente."""
    if not command_exists("zabbix_proxy"):
        return
    current_version = installed_proxy_version()
    if current_version != target_version:
        raise RuntimeError(
            "Ja existe um Zabbix Proxy {} instalado; foi selecionado {}. "
            "Por seguranca, o instalador nao faz upgrade/downgrade "
            "automatico. Realize uma migracao planejada e faca backup "
            "da base SQLite, que pode ser recriada ao mudar de versao."
            .format(current_version, target_version)
        )


def frequency_option(zabbix_version):
    return "ConfigFrequency" if zabbix_version == "6.0" else "ProxyConfigFrequency"


def repair_existing_config():
    """Corrige um conf existente sem reinstalar pacotes nem alterar o SQLite."""
    version = installed_proxy_version()
    conf = Path("/etc/zabbix/zabbix_proxy.conf")
    if not conf.exists():
        raise RuntimeError("Arquivo nao encontrado: {}".format(conf))
    original = conf.read_text(encoding="utf-8", errors="replace")
    content = deduplicate_config(original)
    content = remove_config_keys(content, ["ConfigFrequency", "ProxyConfigFrequency"])
    content = set_config_value(content, frequency_option(version), "60")
    if content != original:
        backup_file(str(conf))
        conf.write_text(content, encoding="utf-8")
        print("Configuracao corrigida para Zabbix {}: {}".format(version, conf))
    else:
        print("Configuracao ja esta normalizada: {}".format(conf))
    print("Agora execute: systemctl restart zabbix-proxy")
    print("E valide: journalctl -u zabbix-proxy -n 50 --no-pager")


def prepare_sqlite_directory(db_path):
    db_file = Path(db_path)
    if not db_file.is_absolute():
        raise RuntimeError("O caminho do banco SQLite precisa ser absoluto (iniciar com /).")
    db_dir = db_file.parent
    db_dir.mkdir(parents=True, exist_ok=True)
    # Nao altera ownership recursivamente de bancos existentes.
    run(["chown", "zabbix:zabbix", str(db_dir)])
    run(["chmod", "750", str(db_dir)])
    print(f"Diretorio preparado: {db_dir}")
    print("Se o SQLite nao existir, o Zabbix Proxy o criara no primeiro start.")


def configure_proxy(conf_path, proxy_name, server_addr, proxy_mode, db_path, zabbix_version):
    conf = Path(conf_path)
    if not conf.exists():
        raise RuntimeError(f"Arquivo nao encontrado: {conf_path}")
    original = conf.read_text(encoding="utf-8", errors="replace")
    content = original
    # Remove a configuracao antiga, independentemente da versao anterior.
    content = remove_config_keys(content, ["ConfigFrequency", "ProxyConfigFrequency"])
    options = {
        "ProxyMode": proxy_mode,
        "Server": server_addr,
        "Hostname": proxy_name,
        "DBName": db_path,
        "LogFile": "/var/log/zabbix/zabbix_proxy.log",
        "PidFile": "/run/zabbix/zabbix_proxy.pid",
        "DataSenderFrequency": "1",
        "Timeout": "30",
    }
    # Zabbix 6.0 aceita ConfigFrequency; a partir do 6.4 use ProxyConfigFrequency.
    frequency_key = frequency_option(zabbix_version)
    options[frequency_key] = "60"
    for key, value in options.items():
        content = set_config_value(content, key, value)
    content = remove_config_keys(content, [
        "DBHost", "DBPort", "DBUser", "DBPassword", "DBSchema", "DBSocket"
    ])
    content = deduplicate_config(content)
    if content != original:
        backup_file(conf_path)
        conf.write_text(content, encoding="utf-8")
        print("Arquivo configurado: {}".format(conf_path))
    else:
        print("Arquivo ja estava correto: {}".format(conf_path))


def enable_and_start():
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "zabbix-proxy"])
    run(["systemctl", "restart", "zabbix-proxy"])
    run(["systemctl", "status", "zabbix-proxy", "--no-pager", "-l"], check=False)
    if subprocess.run(["systemctl", "is-active", "--quiet", "zabbix-proxy"]).returncode:
        raise RuntimeError(
            "O Zabbix Proxy nao ficou ativo. Verifique: "
            "journalctl -u zabbix-proxy -n 80 --no-pager"
        )


def show_summary(proxy_name, server_addr, proxy_mode, db_path, os_info, zabbix_version):
    print("\n" + "=" * 70)
    print("INSTALACAO FINALIZADA")
    print("=" * 70)
    print(f"SO detectado       : {os_info['pretty_name']}")
    print(f"Versao do Proxy    : {zabbix_version}")
    print(f"Nome do Proxy      : {proxy_name}")
    print(f"Zabbix Server      : {server_addr}")
    print(f"Modo do Proxy      : {'Ativo' if proxy_mode == '0' else 'Passivo'}")
    print(f"Banco SQLite       : {db_path}")
    print("Confira se o nome do proxy coincide exatamente com o cadastrado no frontend.")


def main():
    ensure_root()
    print("=" * 70)
    print("INSTALADOR ZABBIX PROXY COM SQLITE")
    print("=" * 70)
    os_info = detect_os()
    print(f"\nSO detectado automaticamente: {os_info['pretty_name']}")
    ask("Qual SO vai ser instalado", default=os_info["pretty_name"], required=False)
    zabbix_version = ask(
        "Qual versao do Proxy que vou instalar", default="7.0", allowed=SUPPORTED_ZABBIX
    )
    proxy_name = ask("Qual nome que vou colocar no proxy")
    server_addr = ask("Qual IP ou DNS do Zabbix Server")
    proxy_mode = ask("Modo do proxy (0=Ativo / 1=Passivo)", default="0", allowed=["0", "1"])
    db_path = ask("Caminho do arquivo SQLite", default="/var/lib/zabbix/zabbix_proxy.db")
    print("\nIniciando instalacao...")
    prevent_unintended_upgrade(zabbix_version)
    install_prereqs(os_info)
    install_zabbix_repo(os_info, zabbix_version)
    install_proxy(os_info)
    actual_version = installed_proxy_version()
    if actual_version != zabbix_version:
        raise RuntimeError(
            "Versao instalada do Proxy ({}) diferente da selecionada ({}). "
            "Verifique o repositorio e os pacotes antes de configurar.".format(
                actual_version, zabbix_version
            )
        )
    prepare_sqlite_directory(db_path)
    configure_proxy(
        "/etc/zabbix/zabbix_proxy.conf", proxy_name, server_addr, proxy_mode, db_path, zabbix_version
    )
    enable_and_start()
    show_summary(proxy_name, server_addr, proxy_mode, db_path, os_info, zabbix_version)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "--repair-config":
            ensure_root()
            repair_existing_config()
        elif len(sys.argv) == 1:
            main()
        else:
            print("Uso: python3 install_zabbix_proxy.py [--repair-config]")
            sys.exit(2)
    except KeyboardInterrupt:
        print("\nExecucao cancelada pelo usuario.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nERRO: {exc}")
        sys.exit(1)
