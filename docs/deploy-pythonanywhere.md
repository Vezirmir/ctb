# Бесплатный запуск на PythonAnywhere

Сайт будет доступен по адресу `https://ВАШ_ЛОГИН.pythonanywhere.com`. Карта не нужна.
Данные хранятся в файле базы SQLite на диске PythonAnywhere (512 МБ на аккаунт).
Для тестового периода этого с запасом.

Ниже везде замените `ВАШ_ЛОГИН` на имя пользователя, выбранное при регистрации.

## 1. Регистрация

1. Откройте https://www.pythonanywhere.com/pricing/ и выберите **Create a Beginner account** (бесплатно).
2. Логин станет частью адреса сайта, например `ctb` → `ctb.pythonanywhere.com`.

## Быстрый способ: одна команда

1. Вкладка **Web** → **Add a new web app** → **Next** → **Manual configuration** → **Python 3.12** → **Next**.
2. Вкладка **Consoles** → **Bash**. Вставьте команду и нажмите Enter:

   ```bash
   curl -sSL https://raw.githubusercontent.com/Vezirmir/ctb/claude/youthful-lovelace-yrjgzy/scripts/pythonanywhere_setup.sh | bash
   ```

   Скрипт скачает и установит проект и подготовит базу. Он спросит логин, e-mail и пароль
   администратора: с ними вы будете входить на сайт.
3. Вкладка **Web**: в поле **Virtualenv** впишите `/home/ВАШ_ЛОГИН/ctb/.venv` и нажмите зелёную кнопку **Reload**.

Готово, переходите к шагу 4 «Загрузить данные». Той же командой потом обновляется сайт
после изменений в коде (после неё снова нажмите **Reload**).

Ниже то же самое вручную, если быстрый способ не сработал.

## 2. Скачать проект и установить

На вкладке **Consoles** нажмите **Bash** и выполните команды по очереди:

```bash
git clone -b claude/youthful-lovelace-yrjgzy https://github.com/Vezirmir/ctb.git
cd ctb
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
DJANGO_DEBUG=0 python manage.py collectstatic --noinput
python manage.py createsuperuser
```

- Если репозиторий приватный, `git clone` спросит логин и пароль. Вместо пароля нужен токен GitHub
  (GitHub → Settings → Developer settings → Personal access tokens).
- `createsuperuser` спросит логин, e-mail и пароль. С ними вы будете входить на сайт.

Сгенерируйте секретный ключ и скопируйте его, он понадобится в шаге 3:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 3. Создать сайт

1. Вкладка **Web** → **Add a new web app** → **Next** → **Manual configuration** → **Python 3.12** → **Next**.
2. В разделе **Virtualenv** укажите `/home/ВАШ_ЛОГИН/ctb/.venv`.
3. В разделе **Code** откройте ссылку **WSGI configuration file**, удалите всё содержимое и вставьте:

```python
import os
import sys

path = "/home/ВАШ_ЛОГИН/ctb"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
os.environ["DJANGO_DEBUG"] = "0"
os.environ["DJANGO_SECRET_KEY"] = "ВСТАВЬТЕ_КЛЮЧ_ИЗ_ШАГА_2"
os.environ["DJANGO_ALLOWED_HOSTS"] = "ВАШ_ЛОГИН.pythonanywhere.com"
os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"] = "https://ВАШ_ЛОГИН.pythonanywhere.com"

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
```

4. Нажмите **Save**. Вернитесь на вкладку **Web** и включите **Force HTTPS**.
5. Нажмите зелёную кнопку **Reload**.

## 4. Загрузить данные

1. Откройте `https://ВАШ_ЛОГИН.pythonanywhere.com` и войдите.
2. Перейдите в **Companies** → **Import from Excel**.
3. Загрузите zip-архив папки `2026`.

## 5. Важно для бесплатного аккаунта

- Раз в месяц PythonAnywhere просит подтвердить, что сайт ещё нужен: на вкладке **Web** нажмите
  **Run until 1 month from today**. Иначе сайт отключится (данные при этом не пропадут).
- Если что-то не работает, смотрите **Error log** на вкладке **Web**.

## Обновление после изменений в коде

```bash
cd ~/ctb
source .venv/bin/activate
git pull
pip install -r requirements.txt
python manage.py migrate
DJANGO_DEBUG=0 python manage.py collectstatic --noinput
```

Затем нажмите **Reload** на вкладке **Web**.

## Резервная копия

Вся база лежит в одном файле `~/ctb/db.sqlite3`. Его можно скачать на вкладке **Files**.
