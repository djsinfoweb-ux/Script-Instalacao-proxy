#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import shutil
import subprocess
from pathlib import Path

SUPPORTED_ZABBIX = ["6.0", "6.4", "7.0", "7.2", "7.4"]


def run(cmd, check=True, capture_output=False):
    print(f"\n>> Executando: {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.STDOUT if capture_output else None
    )

    if check and result.returncode != 0:
        if capture_output and result.stdout:
            print(result.stdout)
        raise RuntimeError(f"Erro ao executar comando: {cmd}")

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
        label = prompt
        if default is not None:
            label += f" [{default}]"
        label += ": "

        value = input(label).strip()

        if not value and default is not None:
            value = default

        if required and not value:
            print("Campo obrigatório.")
            continue

        if allowed and value not in allowed:
            print(f"Valor inválido. Opções permitidas: {', '.join(allowed)}")
            continue

        return value


def detect_os():
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        raise RuntimeError("Arquivo /etc/os-release não encontrado. Não foi possível identificar o sistema.")

    data = {}
    for line in os_release.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k] = v.strip().strip('"')

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
        raise RuntimeError(f"Sistema não suportado automaticamente: {pretty_name}")

    return {
        "id": os_id,
        "version": version_id,
        "pretty_name": pretty_name,
        "family": family,
        "major": major
    }


def command_exists(command):
    return shutil.which(command) is not None


def install_prereqs(os_info):
    if os_info["family"] == "debian":
        run("apt-get update")
        run("apt-get install -y wget curl gnupg lsb-release")
    else:
        pkgmgr = "dnf" if command_exists("dnf") else "yum"
        run(f"{pkgmgr} install -y wget curl")


def install_zabbix_repo(os_info, zabbix_version):
    if os_info["id"] == "ubuntu":
        release_pkg = f"zabbix-release_latest+ubuntu{os_info['version']}_all.deb"
        url = f"https://repo.zabbix.com/zabbix/{zabbix_version}/ubuntu/pool/main/z/zabbix-release/{release_pkg}"
        local_file = f"/tmp/{release_pkg}"

        run(f"wget -O {local_file} {url}")
        run(f"dpkg -i {local_file}")
        run("apt-get update")

    elif os_info["id"] == "debian":
        release_pkg = f"zabbix-release_latest+debian{os_info['version']}_all.deb"
        url = f"https://repo.zabbix.com/zabbix/{zabbix_version}/debian/pool/main/z/zabbix-release/{release_pkg}"
        local_file = f"/tmp/{release_pkg}"

        run(f"wget -O {local_file} {url}")
        run(f"dpkg -i {local_file}")
        run("apt-get update")

    elif os_info["id"] in ["rhel", "rocky", "almalinux", "centos"]:
        pkgmgr = "dnf" if command_exists("dnf") else "yum"
        major = os_info["major"]
        distro = os_info["id"]

        if distro == "centos":
            distro = "rhel"

        url = f"https://repo.zabbix.com/zabbix/{zabbix_version}/{distro}/{major}/x86_64/zabbix-release-{zabbix_version}-1.el{major}.noarch.rpm"
        run(f"rpm -Uvh {url}")
        run(f"{pkgmgr} clean all")

    elif os_info["id"] in ["ol", "oracle"]:
        pkgmgr = "dnf" if command_exists("dnf") else "yum"
        major = os_info["major"]
        url = f"https://repo.zabbix.com/zabbix/{zabbix_version}/oraclelinux/{major}/x86_64/zabbix-release-{zabbix_version}-1.el{major}.noarch.rpm"
        run(f"rpm -Uvh {url}")
        run(f"{pkgmgr} clean all")

    else:
        raise RuntimeError(f"Sistema operacional não suportado para instalação automática: {os_info['pretty_name']}")


def install_proxy(os_info):
    if os_info["family"] == "debian":
        run("apt-get install -y zabbix-proxy-sqlite3")
    else:
        pkgmgr = "dnf" if command_exists("dnf") else "yum"
        run(f"{pkgmgr} install -y zabbix-proxy-sqlite3")


def backup_file(file_path):
    path = Path(file_path)
    if path.exists():
        backup = f"{file_path}.bak"
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
            flags=re.MULTILINE
        )
    return content


def prepare_sqlite_directory(db_path):
    db_file = Path(db_path)
    db_dir = db_file.parent

    db_dir.mkdir(parents=True, exist_ok=True)

    run(f"chown -R zabbix:zabbix {db_dir}")
    run(f"chmod 750 {db_dir}")

    print(f"Diretório preparado: {db_dir}")
    print("O arquivo SQLite será criado automaticamente pelo Zabbix Proxy no primeiro start.")


def configure_proxy(conf_path, proxy_name, server_addr, proxy_mode, db_path):
    conf = Path(conf_path)

    if not conf.exists():
        raise RuntimeError(f"Arquivo não encontrado: {conf_path}")

    backup_file(conf_path)

    content = conf.read_text(encoding="utf-8", errors="ignore")

    content = set_config_value(content, "ProxyMode", proxy_mode)
    content = set_config_value(content, "Server", server_addr)
    content = set_config_value(content, "Hostname", proxy_name)
    content = set_config_value(content, "DBName", db_path)
    content = set_config_value(content, "LogFile", "/var/log/zabbix/zabbix_proxy.log")
    content = set_config_value(content, "PidFile", "/run/zabbix/zabbix_proxy.pid")
    content = set_config_value(content, "ConfigFrequency", "60")
    content = set_config_value(content, "DataSenderFrequency", "1")
    content = set_config_value(content, "Timeout", "30")

    content = remove_config_keys(content, [
        "DBHost",
        "DBPort",
        "DBUser",
        "DBPassword",
        "DBSchema",
        "DBSocket"
    ])

    conf.write_text(content, encoding="utf-8")
    print(f"Arquivo configurado: {conf_path}")


def enable_and_start():
    run("systemctl daemon-reload")
    run("systemctl enable zabbix-proxy")
    run("systemctl restart zabbix-proxy")
    run("systemctl status zabbix-proxy --no-pager", check=False)


def show_summary(proxy_name, server_addr, proxy_mode, db_path, os_info, zabbix_version):
    print("\n" + "=" * 70)
    print("INSTALAÇÃO FINALIZADA")
    print("=" * 70)
    print(f"SO detectado        : {os_info['pretty_name']}")
    print(f"Versão do Proxy     : {zabbix_version}")
    print(f"Nome do Proxy       : {proxy_name}")
    print(f"Zabbix Server       : {server_addr}")
    print(f"Modo do Proxy       : {'Ativo' if proxy_mode == '0' else 'Passivo'}")
    print(f"Banco SQLite        : {db_path}")
    print("\nValide no frontend do Zabbix se o nome do proxy está exatamente igual ao cadastrado.")


def main():
    ensure_root()

    print("=" * 70)
    print("INSTALADOR ZABBIX PROXY COM SQLITE")
    print("=" * 70)

    os_info = detect_os()
    print(f"\nSO detectado automaticamente: {os_info['pretty_name']}")

    # Apenas confirmação visual. Não altera a detecção real do sistema.
    ask("Qual SO vai ser instalado", default=os_info["pretty_name"], required=False)

    zabbix_version = ask(
        "Qual versão do Proxy que vou instalar",
        default="7.0",
        allowed=SUPPORTED_ZABBIX
    )

    proxy_name = ask("Qual nome que vou colocar no proxy")
    server_addr = ask("Qual IP ou DNS do Zabbix Server")
    proxy_mode = ask(
        "Modo do proxy (0=Ativo / 1=Passivo)",
        default="0",
        allowed=["0", "1"]
    )

    db_path = ask(
        "Caminho do arquivo SQLite",
        default="/var/lib/zabbix/zabbix_proxy.db"
    )

    print("\nIniciando instalação...")
    install_prereqs(os_info)
    install_zabbix_repo(os_info, zabbix_version)
    install_proxy(os_info)
    prepare_sqlite_directory(db_path)
    configure_proxy(
        conf_path="/etc/zabbix/zabbix_proxy.conf",
        proxy_name=proxy_name,
        server_addr=server_addr,
        proxy_mode=proxy_mode,
        db_path=db_path
    )
    enable_and_start()
    show_summary(proxy_name, server_addr, proxy_mode, db_path, os_info, zabbix_version)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExecução cancelada pelo usuário.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nERRO: {exc}")
        sys.exit(1)
