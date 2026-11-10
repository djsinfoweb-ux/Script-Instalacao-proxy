#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador interativo de Zabbix Proxy com SQLite3.

Corrige o caminho do repositorio para Oracle Linux 8/9 e utiliza
ProxyConfigFrequency nas configuracoes do Zabbix Proxy.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SUPPORTED_ZABBIX = ["6.0", "6.4", "7.0", "7.2", "7.4"]


def run(cmd, check=True, capture_output=False):
    """Executa um comando e interrompe a instalacao se ele falhar."""
    if isinstance(cmd, (list, tuple)):
        display = shlex.join(str(part) for part in cmd)
    else:
        display = str(cmd)
    print(f"\n>> Executando: {display}")
    result = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        text=True,
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
    Zabbix 7.2/7.4 usa /release/<distro>/9/noarch.
    Para 6.0/6.4 o pacote compativel de RHEL e usado como fallback.
    """
    major = os_info["major"]
    os_id = os_info["id"]
    rpm = f"zabbix-release-latest-{zabbix_version}.el{major}.noarch.rpm"

    if zabbix_version in ["7.2", "7.4"]:
        if os_id in ["ol", "oracle"]:
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
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{file_path}.{suffix}.bak"
        shutil.copy2(file_path, backup)
        print(f"Backup criado: {backup}")


def set_config_value(content, key, value):
    pattern = rf"^\s*#?\s*{re.escape(key)}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, replacement, content, flags=re.MULTILINE)
    return content.rstrip() + "\n" + replacement + "\n"


def remove_config_keys(content, keys):
    for key in keys:
        content = re.sub(
            rf"^\s*#?\s*{re.escape(key)}=.*\n?",
            "",
            content,
            flags=re.MULTILINE,
        )
    return content


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


def configure_proxy(conf_path, proxy_name, server_addr, proxy_mode, db_path):
    conf = Path(conf_path)
    if not conf.exists():
        raise RuntimeError(f"Arquivo nao encontrado: {conf_path}")
    backup_file(conf_path)
    content = conf.read_text(encoding="utf-8", errors="ignore")
    # Remove o nome antigo antes de definir o parametro recomendado no Zabbix 7.0.
    content = remove_config_keys(content, ["ConfigFrequency"])
    options = {
        "ProxyMode": proxy_mode,
        "Server": server_addr,
        "Hostname": proxy_name,
        "DBName": db_path,
        "LogFile": "/var/log/zabbix/zabbix_proxy.log",
        "PidFile": "/run/zabbix/zabbix_proxy.pid",
        "ProxyConfigFrequency": "60",
        "DataSenderFrequency": "1",
        "Timeout": "30",
    }
    for key, value in options.items():
        content = set_config_value(content, key, value)
    content = remove_config_keys(content, [
        "DBHost", "DBPort", "DBUser", "DBPassword", "DBSchema", "DBSocket"
    ])
    conf.write_text(content, encoding="utf-8")
    print(f"Arquivo configurado: {conf_path}")


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
    install_prereqs(os_info)
    install_zabbix_repo(os_info, zabbix_version)
    install_proxy(os_info)
    prepare_sqlite_directory(db_path)
    configure_proxy(
        "/etc/zabbix/zabbix_proxy.conf", proxy_name, server_addr, proxy_mode, db_path
    )
    enable_and_start()
    show_summary(proxy_name, server_addr, proxy_mode, db_path, os_info, zabbix_version)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExecucao cancelada pelo usuario.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nERRO: {exc}")
        sys.exit(1)
