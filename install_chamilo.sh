#!/usr/bin/env bash
set -euo pipefail

# ==============================
# ПАРАМЕТРЫ
# ==============================
CHAMILO_VER="1.11.32"
CHAMILO_DIR="/var/www/html/chamilo"

DB_NAME="chamilo_db"
DB_USER="chamilo_user"
DB_PASS="StrongPassword123!"   # ИЗМЕНИТЕ

PHP_VER="8.1"

# ==============================
# ROOT CHECK
# ==============================
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запустите от root: sudo bash install_chamilo.sh"
  exit 1
fi

# ==============================
# OS DETECT
# ==============================
. /etc/os-release
OS_ID="${ID:-}"
OS_VER="${VERSION_ID:-}"
OS_CODENAME="${VERSION_CODENAME:-}"

echo "=== OS: ${OS_ID} ${OS_VER} (${OS_CODENAME}) ==="

# ==============================
# HELPERS
# ==============================
get_ip() {
  # берет первый не-loopback IPv4
  ip -4 addr show | awk '/inet /{print $2}' | cut -d/ -f1 | grep -v '^127\.' | head -n1
}

SERVER_IP="$(get_ip || true)"
if [[ -z "${SERVER_IP}" ]]; then
  SERVER_IP="$(hostname -I | awk '{print $1}' || true)"
fi

# ==============================
# BASE PACKAGES
# ==============================
export DEBIAN_FRONTEND=noninteractive
apt update
apt install -y ca-certificates apt-transport-https curl gnupg lsb-release unzip

# ==============================
# PHP REPO (depends on OS)
# ==============================
if [[ "${OS_ID}" == "debian" ]]; then
  echo "=== Добавляем Sury repo для PHP (Debian) ==="
  curl -fsSL https://packages.sury.org/php/apt.gpg -o /etc/apt/trusted.gpg.d/php.gpg
  echo "deb https://packages.sury.org/php/ ${OS_CODENAME} main" > /etc/apt/sources.list.d/php.list
  apt update
elif [[ "${OS_ID}" == "ubuntu" ]]; then
  echo "=== Добавляем Ondrej PPA для PHP (Ubuntu) ==="
  apt install -y software-properties-common
  add-apt-repository -y ppa:ondrej/php
  apt update
else
  echo "Неподдерживаемая ОС: ${OS_ID}"
  exit 1
fi

# ==============================
# INSTALL STACK
# ==============================
echo "=== Установка Apache + MariaDB + PHP ${PHP_VER} ==="
apt install -y apache2 mariadb-server \
  php${PHP_VER} libapache2-mod-php${PHP_VER} \
  php${PHP_VER}-cli php${PHP_VER}-common php${PHP_VER}-mysql \
  php${PHP_VER}-xml php${PHP_VER}-curl php${PHP_VER}-zip \
  php${PHP_VER}-mbstring php${PHP_VER}-gd php${PHP_VER}-intl \
  php${PHP_VER}-soap php${PHP_VER}-ldap

systemctl enable --now apache2
systemctl enable --now mariadb

a2enmod rewrite
a2enmod php${PHP_VER} 2>/dev/null || true

# Отключить другие php-модули Apache, если есть
for m in /etc/apache2/mods-enabled/php*.load; do
  [[ -e "$m" ]] || continue
  bn="$(basename "$m" .load)"
  [[ "$bn" == "php${PHP_VER}" ]] && continue
  a2dismod "$bn" || true
done

systemctl restart apache2

# ==============================
# DB SETUP
# ==============================
echo "=== Настройка базы данных ==="
mysql <<SQL
CREATE DATABASE IF NOT EXISTS ${DB_NAME}
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost'
  IDENTIFIED BY '${DB_PASS}';

GRANT ALL PRIVILEGES ON ${DB_NAME}.*
  TO '${DB_USER}'@'localhost';

FLUSH PRIVILEGES;
SQL

# ==============================
# DOWNLOAD & DEPLOY CHAMILO
# ==============================
echo "=== Установка Chamilo ${CHAMILO_VER} в ${CHAMILO_DIR} ==="
rm -rf "${CHAMILO_DIR}"
mkdir -p "${CHAMILO_DIR}"

cd /tmp
curl -L -o chamilo.tar.gz \
  "https://github.com/chamilo/chamilo-lms/releases/download/v${CHAMILO_VER}/chamilo-${CHAMILO_VER}.tar.gz"

tar -xzf chamilo.tar.gz -C "${CHAMILO_DIR}" --strip-components=1

chown -R www-data:www-data "${CHAMILO_DIR}"
chmod -R 755 "${CHAMILO_DIR}"

# ==============================
# APACHE VHOST (DocumentRoot /var/www/html, Chamilo in /chamilo)
# ==============================
echo "=== Настройка VirtualHost ==="
cat > /etc/apache2/sites-available/000-default.conf <<EOF
<VirtualHost *:80>
    ServerAdmin webmaster@localhost
    DocumentRoot /var/www/html

    <Directory /var/www/html>
        Options Indexes FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    <Directory /var/www/html/chamilo>
        Options FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    ErrorLog \${APACHE_LOG_DIR}/error.log
    CustomLog \${APACHE_LOG_DIR}/access.log combined
</VirtualHost>
EOF

apachectl configtest
systemctl restart apache2

# ==============================
# PHP TUNING
# ==============================
PHP_INI="/etc/php/${PHP_VER}/apache2/php.ini"
if [[ -f "${PHP_INI}" ]]; then
  sed -i 's/^memory_limit.*/memory_limit = 256M/' "${PHP_INI}" || true
  sed -i 's/^max_execution_time.*/max_execution_time = 300/' "${PHP_INI}" || true
  sed -i 's/^upload_max_filesize.*/upload_max_filesize = 50M/' "${PHP_INI}" || true
  sed -i 's/^post_max_size.*/post_max_size = 50M/' "${PHP_INI}" || true
fi
systemctl restart apache2

# ==============================
# FINAL INFO
# ==============================
echo ""
echo "======================================"
echo "ГОТОВО."
echo "Откройте установщик:"
echo "http://${SERVER_IP}/chamilo/"
echo ""
echo "Данные БД для установщика:"
echo "Host: localhost"
echo "DB:   ${DB_NAME}"
echo "User: ${DB_USER}"
echo "Pass: ${DB_PASS}"
echo "======================================"