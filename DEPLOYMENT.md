# 🚀 DEVELOPMENT GUIDE: Развертывание Mnemo C2 на VPS

## 📋 Подготовка к развертыванию

### На локальной машине:
1. **Проверь все файлы есть:**
   - ✅ `mnemo-bot.service` - systemd конфиг
   - ✅ `run.sh` - скрипт управления ботом
   - ✅ `.env.production` - шаблон конфигурации для VPS
   - ✅ `bot.py` - обновлен для логирования в файл
   - ✅ `db.py` - обновлен для логирования

2. **Проверь что локально работает:**
   ```bash
   pip install -r requirements.txt
   python bot.py
   # Бот должен запуститься без ошибок
   ```

---

## 🌐 Развертывание на VPS

### Шаг 1: Подготовка VPS
```bash
# Подключись к VPS
ssh root@your_vps_ip

# Обновить пакеты
apt update && apt upgrade -y

# Установить Python и зависимости
apt install -y python3 python3-pip python3-venv git

# Создать пользователя для бота
useradd -m -d /home/mnemo -s /bin/bash mnemo

# Создать директорию проекта
mkdir -p /opt/mnemo
chown mnemo:mnemo /opt/mnemo

# Создать директорию для логов
mkdir -p /var/log/mnemo
chown mnemo:mnemo /var/log/mnemo
```

### Шаг 2: Загрузить проект на VPS
```bash
# Из локальной машины, копируем проект
scp -r /path/to/mnemo-c2/* mnemo@your_vps_ip:/opt/mnemo/

# Или если используешь Git:
ssh mnemo@your_vps_ip
cd /opt/mnemo
git clone https://your_repo_url .
```

### Шаг 3: Установить зависимости
```bash
ssh mnemo@your_vps_ip
cd /opt/mnemo

# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt
```

### Шаг 4: Настроить .env
```bash
# Отредактировать .env.production
nano /opt/mnemo/.env.production

# Заполнить BOT_TOKEN и другие параметры:
# BOT_TOKEN=8559722395:AAH1wnWS2rEIxz5uUrBYnNJB2CjeSpZEwsM
# LOG_LEVEL=INFO
# LOG_FILE=/var/log/mnemo/bot.log
# DATABASE_PATH=/opt/mnemo/mnemo.db
# WORDS_JSON_PATH=/opt/mnemo/words.json

# Переименовать в .env
mv /opt/mnemo/.env.production /opt/mnemo/.env

# Выйти из редактора: Ctrl+X -> Y -> Enter
```

### Шаг 5: Установить systemd сервис
```bash
# Копируем файл сервиса
sudo cp /opt/mnemo/mnemo-bot.service /etc/systemd/system/

# Перезагружаем systemd
sudo systemctl daemon-reload

# Включаем автозапуск
sudo systemctl enable mnemo-bot

# Запускаем сервис
sudo systemctl start mnemo-bot

# Проверяем статус
sudo systemctl status mnemo-bot
```

### Шаг 6: Проверить логи
```bash
# Смотреть логи в реальном времени
sudo journalctl -u mnemo-bot -f

# Или через файл логов
tail -f /var/log/mnemo/bot.log
```

---

## 🔧 Полезные команды на VPS

### Управление сервисом через systemd
```bash
# Запустить бот
sudo systemctl start mnemo-bot

# Остановить бот
sudo systemctl stop mnemo-bot

# Перезагрузить бот
sudo systemctl restart mnemo-bot

# Показать статус
sudo systemctl status mnemo-bot

# Смотреть логи (-f для live режима)
sudo journalctl -u mnemo-bot -f
sudo journalctl -u mnemo-bot --lines=100

# Отключить автозапуск
sudo systemctl disable mnemo-bot
```

### Управление через скрипт run.sh
```bash
# Если хочешь управлять вручную (минуя systemd)
cd /opt/mnemo

# Запустить бот
./run.sh start

# Остановить
./run.sh stop

# Перезагрузить
./run.sh restart

# Статус
./run.sh status

# Логи
./run.sh logs
```

---

## 📊 Проверка логирования

### На VPS в systemd журнале:
```bash
sudo journalctl -u mnemo-bot -f

# Ожидай вывода:
# Apr 30 14:23:45 server bot.py[1234]: ✅ Логирование в файл: /var/log/mnemo/bot.log
# Apr 30 14:23:45 server bot.py[1234]: 🔧 Инициализация базы данных...
# Apr 30 14:23:46 server bot.py[1234]: ✅ База данных готова!
```

### В файле логов:
```bash
tail -f /var/log/mnemo/bot.log

# Ожидай вывода:
# 2026-05-02 14:23:45 - root - INFO - ✅ Логирование в файл: /var/log/mnemo/bot.log
# 2026-05-02 14:23:45 - bot - INFO - 🔧 Инициализация базы данных...
# 2026-05-02 14:23:46 - bot - INFO - ✅ База данных готова!
```

---

## 🆘 Решение проблем

### Проблема: "Permission denied" при запуске
```bash
# Решение: дать права пользователю mnemo
sudo chown -R mnemo:mnemo /opt/mnemo
sudo chown -R mnemo:mnemo /var/log/mnemo
chmod +x /opt/mnemo/run.sh
```

### Проблема: Логи не появляются
```bash
# Проверь что LOG_FILE указан в .env
cat /opt/mnemo/.env | grep LOG_FILE

# Проверь права на директорию логов
ls -la /var/log/mnemo/

# Убедись что директория создана
mkdir -p /var/log/mnemo
chown mnemo:mnemo /var/log/mnemo
```

### Проблема: "Connection refused" - бот не отвечает
```bash
# Проверь что сервис запущен
sudo systemctl status mnemo-bot

# Посмотри ошибки в логах
sudo journalctl -u mnemo-bot -n 50

# Убедись что BOT_TOKEN правильный в .env
grep BOT_TOKEN /opt/mnemo/.env
```

---

## 🔄 Резервное копирование

### Создать бэкап данных
```bash
# Архивируем БД и JSON
tar -czf /opt/mnemo/backup-$(date +%Y%m%d).tar.gz \
  /opt/mnemo/mnemo.db \
  /opt/mnemo/words.json

# Копируем на безопасное место
scp mnemo@your_vps_ip:/opt/mnemo/backup-*.tar.gz /local/backup/
```

### Восстановить из бэкапа
```bash
# Остановить бот
sudo systemctl stop mnemo-bot

# Восстановить файлы
tar -xzf backup-20260502.tar.gz -C /

# Запустить бот
sudo systemctl start mnemo-bot
```

---

## 📈 Мониторинг

### Установить uptime мониторинг
```bash
# Проверить что бот работает
systemctl status mnemo-bot

# Настроить напоминание если упадет (в crontab)
crontab -e

# Добавить строку:
*/5 * * * * systemctl is-active --quiet mnemo-bot || systemctl restart mnemo-bot

# Сохранить: Ctrl+X -> Y -> Enter
```

---

## ✅ Чек-лист перед запуском

- [ ] VPS сервер подготовлен (Python, зависимости)
- [ ] Создан пользователь `mnemo`
- [ ] Директории `/opt/mnemo` и `/var/log/mnemo` созданы
- [ ] Проект скопирован на VPS
- [ ] `.env` заполнен с правильным BOT_TOKEN
- [ ] `mnemo-bot.service` установлен в `/etc/systemd/system/`
- [ ] systemd daemon-reload выполнен
- [ ] systemctl enable mnemo-bot выполнен
- [ ] systemctl start mnemo-bot выполнен
- [ ] Проверены логи - нет ошибок
- [ ] Бот отвечает на сообщения в Telegram

---

## 🎯 Что дальше?

1. **Первый запуск**: Проверь что бот отвечает в Telegram
2. **Проверь логирование**: Должны видеть все события
3. **Мониторинг**: Настрой алерты если что-то сломается
4. **Бэкапы**: Регулярно архивируй БД и JSON
5. **Обновления**: Периодически обновляй код (pull, pip install -r requirements.txt, systemctl restart)
