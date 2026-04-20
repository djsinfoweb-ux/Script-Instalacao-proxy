# Instalador Zabbix Proxy com SQLite em Python

Script em Python para automatizar a instalação do **Zabbix Proxy com SQLite** em Linux, suportando Zabbix 6.0+.

---

## 🚀 O que o script faz

* Detecta automaticamente o sistema operacional
* Instala o repositório oficial do Zabbix
* Instala o `zabbix-proxy-sqlite3`
* Configura o proxy automaticamente
* Cria diretório do banco SQLite
* Inicia e habilita o serviço

---

## 🧠 Importante (SQLite)

❗ **Não precisa importar schema**

O próprio Zabbix Proxy cria o banco automaticamente no primeiro start.

---

## 📦 Requisitos

* Python 3
* Acesso root (`sudo`)
* Internet

---

## ▶️ Como usar

```bash
git clone https://github.com/djsinfoweb-ux/Script-Instalacao-proxy.git
cd Script-Instalacao-proxy
chmod +x install_zabbix_proxy.py
sudo python3 install_zabbix_proxy.py
```

---

## 📝 Perguntas do script

```text
Qual versão do Proxy
Nome do Proxy
IP ou DNS do Zabbix Server
Modo (ativo/passivo)
Caminho do banco SQLite
```

---

## ⚙️ Configuração aplicada

```ini
ProxyMode=0
Server=SEU_SERVER
Hostname=NOME_PROXY
DBName=/var/lib/zabbix/zabbix_proxy.db
```

---

## 🐛 Erros comuns

### ❌ 404 no repositório

Errado:

```
/release/ubuntu/
```

Correto:

```
/ubuntu/
```

---

### ❌ Proxy não conecta

Verifique:

```bash
systemctl status zabbix-proxy
tail -f /var/log/zabbix/zabbix_proxy.log
```

---

## 📁 Arquivos importantes

* `/etc/zabbix/zabbix_proxy.conf`
* `/var/lib/zabbix/zabbix_proxy.db`
* `/var/log/zabbix/zabbix_proxy.log`

---

## 💡 Próximos upgrades

* TLS PSK
* Integração via API Zabbix
* Execução automática (sem interação)
* Log de instalação

---

## 👨‍💻 Autor

Projeto para automação de instalação de Zabbix Proxy.
