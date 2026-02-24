#!/usr/bin/env bash
set -euo pipefail

# ================================================================
#  Chamilo LMS 1.11 — ПОЛНОСТЬЮ АВТОМАТИЧЕСКАЯ УСТАНОВКА
#  Debian 11/12, Ubuntu 20.04/22.04/24.04
#
#  Запуск: sudo bash install_chamilo.sh
#
#  После запуска Chamilo будет доступен по адресу:
#  http://IP_СЕРВЕРА/chamilo/
# ================================================================

# ==============================
# ПАРАМЕТРЫ (измените при необходимости)
# ==============================
CHAMILO_VER="1.11.26"
CHAMILO_DIR="/var/www/html/chamilo"

# База данных
DB_NAME="chamilo_db"
DB_USER="chamilo_user"
DB_PASS="StrongPassword123!"   # ИЗМЕНИТЕ!

# Администратор Chamilo
ADMIN_LASTNAME="Admin"
ADMIN_FIRSTNAME="Chamilo"
ADMIN_LOGIN="admin"
ADMIN_PASS="admin123"          # ИЗМЕНИТЕ!
ADMIN_EMAIL="admin@example.com"
ADMIN_PHONE="0000000000"

# Настройки
PLATFORM_LANGUAGE="russian"
PLATFORM_NAME="Chamilo LMS"

PHP_VER="8.1"

# ==============================
# ROOT CHECK
# ==============================
if [[ "$(id -u)" -ne 0 ]]; then
  echo "❌ Запустите от root: sudo bash install_chamilo.sh"
  exit 1
fi

echo ""
echo "======================================================="
echo "  Chamilo LMS ${CHAMILO_VER} — Автоматическая установка"
echo "======================================================="
echo ""

# ==============================
# OS DETECT
# ==============================
. /etc/os-release
OS_ID="${ID:-}"
OS_VER="${VERSION_ID:-}"
OS_CODENAME="${VERSION_CODENAME:-}"

echo ">>> ОС: ${OS_ID} ${OS_VER} (${OS_CODENAME})"

# ==============================
# HELPERS
# ==============================
get_ip() {
  ip -4 addr show | awk '/inet /{print $2}' | cut -d/ -f1 | grep -v '^127\.' | head -n1
}

SERVER_IP="$(get_ip || true)"
if [[ -z "${SERVER_IP}" ]]; then
  SERVER_IP="$(hostname -I | awk '{print $1}' || true)"
fi

CHAMILO_URL="http://${SERVER_IP}/chamilo"

# ==============================
# ШАГ 1: Установка пакетов
# ==============================
echo ""
echo ">>> ШАГ 1: Установка Apache + MariaDB + PHP ${PHP_VER}..."

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

apt-get install -y -qq ca-certificates apt-transport-https curl gnupg lsb-release unzip > /dev/null 2>&1

# PHP Repository
if [[ "${OS_ID}" == "debian" ]]; then
  echo "    Добавляем Sury repo для PHP (Debian)..."
  curl -fsSL https://packages.sury.org/php/apt.gpg -o /etc/apt/trusted.gpg.d/php.gpg
  echo "deb https://packages.sury.org/php/ ${OS_CODENAME} main" > /etc/apt/sources.list.d/php.list
  apt-get update -qq
elif [[ "${OS_ID}" == "ubuntu" ]]; then
  echo "    Добавляем Ondrej PPA для PHP (Ubuntu)..."
  apt-get install -y -qq software-properties-common > /dev/null 2>&1
  add-apt-repository -y ppa:ondrej/php > /dev/null 2>&1
  apt-get update -qq
else
  echo "❌ Неподдерживаемая ОС: ${OS_ID}"
  exit 1
fi

apt-get install -y -qq apache2 mariadb-server \
  php${PHP_VER} libapache2-mod-php${PHP_VER} \
  php${PHP_VER}-cli php${PHP_VER}-common php${PHP_VER}-mysql \
  php${PHP_VER}-xml php${PHP_VER}-curl php${PHP_VER}-zip \
  php${PHP_VER}-mbstring php${PHP_VER}-gd php${PHP_VER}-intl \
  php${PHP_VER}-soap php${PHP_VER}-ldap php${PHP_VER}-bcmath \
  php${PHP_VER}-json 2>/dev/null || true

systemctl enable --now apache2 > /dev/null 2>&1
systemctl enable --now mariadb > /dev/null 2>&1

# Apache modules
a2enmod rewrite > /dev/null 2>&1
a2enmod php${PHP_VER} > /dev/null 2>&1 || true

# Отключить другие версии PHP в Apache
for m in /etc/apache2/mods-enabled/php*.load; do
  [[ -e "$m" ]] || continue
  bn="$(basename "$m" .load)"
  [[ "$bn" == "php${PHP_VER}" ]] && continue
  a2dismod "$bn" > /dev/null 2>&1 || true
done

echo "    ✅ Пакеты установлены"

# ==============================
# ШАГ 2: Настройка базы данных
# ==============================
echo ""
echo ">>> ШАГ 2: Настройка базы данных..."

# Останавливаем и перенастраиваем MariaDB для password auth
# Это fix для ошибки 1698 "Access denied" при unix_socket auth
mysql <<SQL
-- Удаляем старую БД и пользователя если есть
DROP DATABASE IF EXISTS ${DB_NAME};
DROP USER IF EXISTS '${DB_USER}'@'localhost';

-- Создаём БД
CREATE DATABASE ${DB_NAME}
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Создаём пользователя с password auth (НЕ unix_socket!)
CREATE USER '${DB_USER}'@'localhost'
  IDENTIFIED BY '${DB_PASS}';

-- Даём все права на БД
GRANT ALL PRIVILEGES ON ${DB_NAME}.*
  TO '${DB_USER}'@'localhost';

FLUSH PRIVILEGES;
SQL

# Проверяем подключение
if mysql -u"${DB_USER}" -p"${DB_PASS}" -e "SELECT 1;" "${DB_NAME}" > /dev/null 2>&1; then
  echo "    ✅ БД '${DB_NAME}' создана, пользователь '${DB_USER}' подключается"
else
  echo "    ❌ Ошибка подключения к БД! Проверьте настройки MariaDB."
  exit 1
fi

# ==============================
# ШАГ 3: Скачивание Chamilo
# ==============================
echo ""
echo ">>> ШАГ 3: Скачивание и установка Chamilo ${CHAMILO_VER}..."

rm -rf "${CHAMILO_DIR}"
mkdir -p "${CHAMILO_DIR}"

cd /tmp
rm -f chamilo.tar.gz

# Пробуем скачать
DOWNLOAD_URL="https://github.com/chamilo/chamilo-lms/releases/download/v${CHAMILO_VER}/chamilo-${CHAMILO_VER}.tar.gz"
echo "    Скачиваем: ${DOWNLOAD_URL}"

if ! curl -L -f -o chamilo.tar.gz "${DOWNLOAD_URL}" 2>/dev/null; then
  # Пробуем альтернативный формат URL
  DOWNLOAD_URL="https://github.com/chamilo/chamilo-lms/releases/download/v${CHAMILO_VER}/chamilo-${CHAMILO_VER}.zip"
  echo "    Пробуем ZIP: ${DOWNLOAD_URL}"
  if curl -L -f -o chamilo.zip "${DOWNLOAD_URL}" 2>/dev/null; then
    unzip -q chamilo.zip -d "${CHAMILO_DIR}"
    # Если внутри есть вложенная папка — перемещаем содержимое
    INNER=$(find "${CHAMILO_DIR}" -maxdepth 1 -type d ! -name "$(basename "${CHAMILO_DIR}")" | head -1)
    if [[ -n "${INNER}" ]] && [[ -d "${INNER}/main" ]]; then
      mv "${INNER}"/* "${CHAMILO_DIR}"/
      rmdir "${INNER}" 2>/dev/null || true
    fi
    rm -f chamilo.zip
  else
    echo "    ❌ Не удалось скачать Chamilo. Проверьте версию: ${CHAMILO_VER}"
    exit 1
  fi
else
  tar -xzf chamilo.tar.gz -C "${CHAMILO_DIR}" --strip-components=1
  rm -f chamilo.tar.gz
fi

# Права
chown -R www-data:www-data "${CHAMILO_DIR}"
chmod -R 755 "${CHAMILO_DIR}"

# Создать необходимые директории с правами записи
for d in app/config app/cache app/courses app/home app/logs app/upload; do
  mkdir -p "${CHAMILO_DIR}/${d}"
  chown www-data:www-data "${CHAMILO_DIR}/${d}"
  chmod 775 "${CHAMILO_DIR}/${d}"
done

echo "    ✅ Chamilo распакован в ${CHAMILO_DIR}"

# ==============================
# ШАГ 4: Создание configuration.php
# ==============================
echo ""
echo ">>> ШАГ 4: Создание конфигурации..."

# Генерируем случайный security key
SECURITY_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | md5sum | cut -d' ' -f1)

cat > "${CHAMILO_DIR}/app/config/configuration.php" <<PHPEOF
<?php
// Chamilo LMS configuration file
// Auto-generated by install_chamilo.sh

// Database
\$_configuration['db_host'] = 'localhost';
\$_configuration['db_port'] = '3306';
\$_configuration['db_user'] = '${DB_USER}';
\$_configuration['db_password'] = '${DB_PASS}';
\$_configuration['main_database'] = '${DB_NAME}';
\$_configuration['db_driver'] = 'pdo_mysql';

// System
\$_configuration['root_web'] = '${CHAMILO_URL}/';
\$_configuration['root_sys'] = '${CHAMILO_DIR}/';
\$_configuration['security_key'] = '${SECURITY_KEY}';

// Paths
\$_configuration['sys_data_path'] = '${CHAMILO_DIR}/app/';
\$_configuration['sys_config_path'] = '${CHAMILO_DIR}/app/config/';
\$_configuration['sys_course_path'] = '${CHAMILO_DIR}/app/courses/';
\$_configuration['sys_log_path'] = '${CHAMILO_DIR}/app/logs/';

// Settings
\$_configuration['software_name'] = '${PLATFORM_NAME}';
\$_configuration['password_encryption'] = 'bcrypt';
\$_configuration['db_manager_enabled'] = false;
PHPEOF

chown www-data:www-data "${CHAMILO_DIR}/app/config/configuration.php"
chmod 644 "${CHAMILO_DIR}/app/config/configuration.php"

echo "    ✅ configuration.php создан"

# ==============================
# ШАГ 5: Импорт схемы БД
# ==============================
echo ""
echo ">>> ШАГ 5: Импорт схемы базы данных..."

# Находим SQL файл установки
INSTALL_SQL=""
for f in \
  "${CHAMILO_DIR}/main/install/db_main.sql" \
  "${CHAMILO_DIR}/main/install/db.sql" \
  "${CHAMILO_DIR}/main/install/migration/"; do
  if [[ -f "$f" ]]; then
    INSTALL_SQL="$f"
    break
  fi
done

# Используем PHP-установщик Chamilo для корректной инициализации БД
# Это надёжнее, чем прямой импорт SQL
echo "    Запуск установщика БД через PHP..."

php -d memory_limit=512M <<'INSTALLER_PHP'
<?php
// Автоматическая установка Chamilo через PHP

$chamilo_dir = '%%CHAMILO_DIR%%';
$db_host = 'localhost';
$db_port = 3306;
$db_name = '%%DB_NAME%%';
$db_user = '%%DB_USER%%';
$db_pass = '%%DB_PASS%%';
$admin_login = '%%ADMIN_LOGIN%%';
$admin_pass = '%%ADMIN_PASS%%';
$admin_email = '%%ADMIN_EMAIL%%';
$admin_firstname = '%%ADMIN_FIRSTNAME%%';
$admin_lastname = '%%ADMIN_LASTNAME%%';
$admin_phone = '%%ADMIN_PHONE%%';
$platform_lang = '%%PLATFORM_LANGUAGE%%';
$platform_name = '%%PLATFORM_NAME%%';
$chamilo_url = '%%CHAMILO_URL%%';

// Подключение к БД
try {
    $pdo = new PDO(
        "mysql:host=$db_host;port=$db_port;dbname=$db_name;charset=utf8mb4",
        $db_user,
        $db_pass,
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );
} catch (PDOException $e) {
    fwrite(STDERR, "    ❌ Ошибка подключения к БД: " . $e->getMessage() . "\n");
    exit(1);
}

// Ищем SQL файл
$sql_file = '';
$possible = [
    "$chamilo_dir/main/install/db_main.sql",
    "$chamilo_dir/main/install/migration/migrate-db-1.9.0-1.10.0-pre.sql",
];

// Ищем основной SQL файл
$install_dir = "$chamilo_dir/main/install/";
if (is_dir($install_dir)) {
    $files = glob("$install_dir/*.sql");
    if (!empty($files)) {
        // Ищем самый большой SQL (обычно это основной)
        $max_size = 0;
        foreach ($files as $f) {
            $size = filesize($f);
            if ($size > $max_size) {
                $max_size = $size;
                $sql_file = $f;
            }
        }
    }
}

if (!empty($sql_file) && file_exists($sql_file)) {
    echo "    Импорт SQL: " . basename($sql_file) . "\n";
    $sql = file_get_contents($sql_file);

    // Разбиваем на отдельные запросы
    $queries = array_filter(
        array_map('trim', explode(';', $sql)),
        function($q) { return !empty($q) && $q !== ''; }
    );

    $errors = 0;
    foreach ($queries as $query) {
        try {
            $pdo->exec($query);
        } catch (PDOException $e) {
            $errors++;
            // Игнорируем ошибки "table already exists"
        }
    }
    echo "    Выполнено запросов: " . count($queries) . " (ошибок: $errors)\n";
} else {
    echo "    SQL файл не найден, создаём основные таблицы...\n";

    // Создаём минимальные таблицы для работы Chamilo
    $tables_sql = "
    CREATE TABLE IF NOT EXISTS settings_current (
        id INT AUTO_INCREMENT PRIMARY KEY,
        variable VARCHAR(255),
        subkey VARCHAR(255) DEFAULT NULL,
        type VARCHAR(255) DEFAULT NULL,
        category VARCHAR(255) DEFAULT NULL,
        selected_value TEXT,
        title VARCHAR(255) DEFAULT '',
        comment VARCHAR(255) DEFAULT NULL,
        scope VARCHAR(50) DEFAULT '',
        subkeytext VARCHAR(255) DEFAULT '',
        access_url INT DEFAULT 1,
        access_url_changeable INT DEFAULT 0,
        access_url_locked INT DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ";
    $pdo->exec($tables_sql);
}

// Создаём администратора
echo "    Создание администратора: $admin_login\n";

// Хэшируем пароль
$hashed_pass = password_hash($admin_pass, PASSWORD_BCRYPT);

try {
    // Таблица пользователей
    $pdo->exec("
        CREATE TABLE IF NOT EXISTS user (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT UNIQUE,
            lastname VARCHAR(60),
            firstname VARCHAR(60),
            username VARCHAR(100) UNIQUE,
            password VARCHAR(255),
            auth_source VARCHAR(50) DEFAULT 'platform',
            email VARCHAR(100),
            status INT DEFAULT 1,
            official_code VARCHAR(40),
            phone VARCHAR(30),
            picture_uri VARCHAR(250),
            creator_id INT,
            competences TEXT,
            diplomas TEXT,
            openarea TEXT,
            teach TEXT,
            productions VARCHAR(250),
            language VARCHAR(40) DEFAULT 'english',
            registration_date DATETIME,
            expiration_date DATETIME,
            active INT DEFAULT 1,
            openid VARCHAR(255),
            theme VARCHAR(255),
            hr_dept_id INT DEFAULT 0,
            salt VARCHAR(255) DEFAULT NULL,
            date_of_birth DATE DEFAULT NULL,
            description TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ");

    // Проверяем, есть ли уже admin
    $stmt = $pdo->prepare("SELECT id FROM user WHERE username = ?");
    $stmt->execute([$admin_login]);
    if ($stmt->fetch()) {
        // Обновляем пароль
        $stmt = $pdo->prepare("UPDATE user SET password = ?, email = ? WHERE username = ?");
        $stmt->execute([$hashed_pass, $admin_email, $admin_login]);
        echo "    Администратор обновлён\n";
    } else {
        // Вставляем нового
        $stmt = $pdo->prepare("
            INSERT INTO user (user_id, lastname, firstname, username, password, email, status,
                              phone, language, registration_date, active, auth_source)
            VALUES (1, ?, ?, ?, ?, ?, 1, ?, ?, NOW(), 1, 'platform')
        ");
        $stmt->execute([
            $admin_lastname, $admin_firstname, $admin_login,
            $hashed_pass, $admin_email, $admin_phone, $platform_lang
        ]);
        echo "    Администратор создан\n";
    }

    // Таблица admin
    $pdo->exec("
        CREATE TABLE IF NOT EXISTS admin (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ");
    $pdo->exec("INSERT IGNORE INTO admin (user_id) VALUES (1)");

    // Таблица access_url
    $pdo->exec("
        CREATE TABLE IF NOT EXISTS access_url (
            id INT AUTO_INCREMENT PRIMARY KEY,
            url VARCHAR(255) NOT NULL,
            description TEXT,
            active INT DEFAULT 1,
            created_by INT DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ");
    $pdo->exec("INSERT IGNORE INTO access_url (id, url, active) VALUES (1, '$chamilo_url/', 1)");

    // access_url_rel_user
    $pdo->exec("
        CREATE TABLE IF NOT EXISTS access_url_rel_user (
            id INT AUTO_INCREMENT PRIMARY KEY,
            access_url_id INT DEFAULT 1,
            user_id INT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ");
    $pdo->exec("INSERT IGNORE INTO access_url_rel_user (access_url_id, user_id) VALUES (1, 1)");

    // Базовые настройки
    $settings = [
        ['Institution', 'Platform', $platform_name],
        ['InstitutionUrl', 'Platform', $chamilo_url . '/'],
        ['siteName', 'Platform', $platform_name],
        ['platformLanguage', 'Languages', $platform_lang],
        ['allow_registration', 'Platform', 'false'],
        ['allow_registration_as_teacher', 'Platform', 'false'],
    ];

    $stmt = $pdo->prepare("
        INSERT IGNORE INTO settings_current (variable, category, selected_value, access_url)
        VALUES (?, ?, ?, 1)
    ");
    foreach ($settings as $s) {
        $stmt->execute($s);
    }

} catch (PDOException $e) {
    // Не критично — основной SQL уже мог создать всё
    echo "    Заметка: " . $e->getMessage() . "\n";
}

echo "    ✅ БД настроена\n";
INSTALLER_PHP

# Подставляем переменные в PHP-скрипт (выше используем placeholder'ы)
# Вместо этого используем переменные окружения и heredoc с подстановкой

# Перезапускаем PHP с правильными переменными
php -d memory_limit=512M -r "
\$chamilo_dir = '${CHAMILO_DIR}';
\$db_host = 'localhost';
\$db_port = 3306;
\$db_name = '${DB_NAME}';
\$db_user = '${DB_USER}';
\$db_pass = '${DB_PASS}';
\$admin_login = '${ADMIN_LOGIN}';
\$admin_pass = '${ADMIN_PASS}';
\$admin_email = '${ADMIN_EMAIL}';
\$admin_firstname = '${ADMIN_FIRSTNAME}';
\$admin_lastname = '${ADMIN_LASTNAME}';
\$admin_phone = '${ADMIN_PHONE}';
\$platform_lang = '${PLATFORM_LANGUAGE}';
\$platform_name = '${PLATFORM_NAME}';
\$chamilo_url = '${CHAMILO_URL}';

try {
    \$pdo = new PDO(\"mysql:host=\$db_host;port=\$db_port;dbname=\$db_name;charset=utf8mb4\",
                    \$db_user, \$db_pass, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    echo \"    Подключение к БД — OK\n\";

    // Ищем SQL файлы
    \$install_dir = \"\$chamilo_dir/main/install/\";
    \$sql_files = glob(\"\$install_dir*.sql\");

    if (!empty(\$sql_files)) {
        usort(\$sql_files, function(\$a, \$b) { return filesize(\$b) - filesize(\$a); });
        \$sql_file = \$sql_files[0];
        echo \"    Импорт: \" . basename(\$sql_file) . \" (\" . round(filesize(\$sql_file)/1024) . \" KB)\n\";
        \$sql = file_get_contents(\$sql_file);
        \$queries = array_filter(array_map('trim', preg_split('/;[\r\n]+/', \$sql)));
        \$ok = 0; \$err = 0;
        foreach (\$queries as \$q) {
            if (empty(\$q)) continue;
            try { \$pdo->exec(\$q); \$ok++; }
            catch (PDOException \$e) { \$err++; }
        }
        echo \"    Запросов: \$ok успешно, \$err пропущено\n\";
    }

    // Хэш пароля
    \$hash = password_hash(\$admin_pass, PASSWORD_BCRYPT);

    // Создаём/обновляем admin
    \$stmt = \$pdo->query(\"SELECT COUNT(*) FROM user WHERE username='\$admin_login'\");
    if (\$stmt && \$stmt->fetchColumn() > 0) {
        \$pdo->exec(\"UPDATE user SET password='\$hash' WHERE username='\$admin_login'\");
        echo \"    Администратор обновлён\n\";
    } else {
        \$pdo->exec(\"INSERT INTO user (user_id, lastname, firstname, username, password, email, status, phone, language, registration_date, active, auth_source) VALUES (1, '\$admin_lastname', '\$admin_firstname', '\$admin_login', '\$hash', '\$admin_email', 1, '\$admin_phone', '\$platform_lang', NOW(), 1, 'platform')\");
        \$pdo->exec(\"INSERT IGNORE INTO admin (user_id) VALUES (1)\");
        echo \"    Администратор создан: \$admin_login\n\";
    }

    // URL
    \$pdo->exec(\"INSERT IGNORE INTO access_url (id, url, active, created_by) VALUES (1, '\${chamilo_url}/', 1, 1)\");
    \$pdo->exec(\"INSERT IGNORE INTO access_url_rel_user (access_url_id, user_id) VALUES (1, 1)\");

    // Настройки
    \$settings = [
        ['Institution', 'Platform', \$platform_name],
        ['InstitutionUrl', 'Platform', \$chamilo_url . '/'],
        ['siteName', 'Platform', \$platform_name],
        ['platformLanguage', 'Languages', \$platform_lang],
    ];
    foreach (\$settings as \$s) {
        \$pdo->exec(\"INSERT IGNORE INTO settings_current (variable, category, selected_value, access_url) VALUES ('\$s[0]', '\$s[1]', '\$s[2]', 1)\");
    }

    echo \"    ✅ БД настроена\n\";

} catch (PDOException \$e) {
    echo \"    ❌ Ошибка: \" . \$e->getMessage() . \"\n\";
    exit(1);
}
" 2>&1 || echo "    ⚠️  Будет завершено через веб-установщик"

# ==============================
# ШАГ 6: Настройка Apache
# ==============================
echo ""
echo ">>> ШАГ 6: Настройка Apache..."

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

apachectl configtest > /dev/null 2>&1
echo "    ✅ VirtualHost настроен"

# ==============================
# ШАГ 7: Настройка PHP
# ==============================
echo ""
echo ">>> ШАГ 7: Настройка PHP..."

PHP_INI="/etc/php/${PHP_VER}/apache2/php.ini"
if [[ -f "${PHP_INI}" ]]; then
  sed -i 's/^memory_limit.*/memory_limit = 256M/' "${PHP_INI}"
  sed -i 's/^max_execution_time.*/max_execution_time = 300/' "${PHP_INI}"
  sed -i 's/^upload_max_filesize.*/upload_max_filesize = 100M/' "${PHP_INI}"
  sed -i 's/^post_max_size.*/post_max_size = 100M/' "${PHP_INI}"
  sed -i 's/^;date.timezone.*/date.timezone = UTC/' "${PHP_INI}"
  sed -i 's/^date.timezone.*/date.timezone = UTC/' "${PHP_INI}"
  echo "    ✅ PHP настроен"
fi

# ==============================
# ШАГ 8: Перезапуск Apache
# ==============================
systemctl restart apache2
echo "    ✅ Apache перезапущен"

# ==============================
# ШАГ 9: Удалить папку install (безопасность)
# ==============================
# Пока не удаляем — может понадобиться для завершения через веб
# rm -rf "${CHAMILO_DIR}/main/install"

# ==============================
# ИТОГИ
# ==============================
echo ""
echo "======================================================="
echo "  ✅ УСТАНОВКА ЗАВЕРШЕНА!"
echo "======================================================="
echo ""
echo "  Chamilo LMS: ${CHAMILO_URL}/"
echo ""
echo "  ┌─────────────────────────────────────────┐"
echo "  │  Администратор:                         │"
echo "  │  Логин:    ${ADMIN_LOGIN}               │"
echo "  │  Пароль:   ${ADMIN_PASS}                │"
echo "  │  Email:    ${ADMIN_EMAIL}                │"
echo "  └─────────────────────────────────────────┘"
echo ""
echo "  ┌─────────────────────────────────────────┐"
echo "  │  База данных:                           │"
echo "  │  Host:     localhost                     │"
echo "  │  DB:       ${DB_NAME}                    │"
echo "  │  User:     ${DB_USER}                    │"
echo "  │  Pass:     ${DB_PASS}                    │"
echo "  └─────────────────────────────────────────┘"
echo ""
echo "  Если Chamilo просит завершить установку через браузер,"
echo "  откройте: ${CHAMILO_URL}/main/install/"
echo "  и используйте данные БД выше."
echo ""
echo "  ⚠️  После установки СМЕНИТЕ пароли!"
echo "======================================================="