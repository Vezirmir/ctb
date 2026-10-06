#!/bin/bash
# One-command setup (and update) of the CTB site on a PythonAnywhere account.
# Run in a PythonAnywhere Bash console after creating a "Manual configuration" web app:
#   curl -sSL https://raw.githubusercontent.com/Vezirmir/ctb/claude/youthful-lovelace-yrjgzy/scripts/pythonanywhere_setup.sh | bash
set -euo pipefail

REPO="https://github.com/Vezirmir/ctb.git"
BRANCH="${CTB_BRANCH:-claude/youthful-lovelace-yrjgzy}"
PYTHON="${CTB_PYTHON:-python3.13}"
APP_DIR="$HOME/ctb"
ME="$(whoami)"
HOSTS="$ME.pythonanywhere.com,$ME.eu.pythonanywhere.com"
ORIGINS="https://$ME.pythonanywhere.com,https://$ME.eu.pythonanywhere.com"

echo "==> 1/6 Downloading the project"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch -q origin "$BRANCH"
    git -C "$APP_DIR" checkout -q "$BRANCH"
    git -C "$APP_DIR" pull -q --ff-only origin "$BRANCH"
else
    git clone -q -b "$BRANCH" "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> 2/6 Installing packages (takes a minute or two)"
# Recreate the virtualenv if it was made with another Python version.
if [ -x .venv/bin/python ] && [ "$(.venv/bin/python -c 'import sys; print(sys.version_info[:2])')" != "$("$PYTHON" -c 'import sys; print(sys.version_info[:2])')" ]; then
    rm -rf .venv
fi
[ -d .venv ] || "$PYTHON" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "==> 3/6 Preparing the database"
[ -f .secret_key ] || python -c "import secrets; print(secrets.token_urlsafe(50))" > .secret_key
chmod 600 .secret_key
python manage.py migrate --noinput
DJANGO_DEBUG=0 DJANGO_SECRET_KEY=collectstatic python manage.py collectstatic --noinput -v0

echo "==> 4/6 Administrator account"
if python manage.py shell -v 0 -c "from django.contrib.auth import get_user_model as g; import sys; sys.exit(0 if g().objects.filter(is_superuser=True).exists() else 1)"; then
    echo "    already exists, skipping"
else
    echo "    Choose the login and password you will use on the site:"
    python manage.py createsuperuser < /dev/tty
fi

echo "==> 5/6 Web app configuration"
shopt -s nullglob
WSGI_FILES=(/var/www/*_wsgi.py)
if [ ${#WSGI_FILES[@]} -ne 1 ]; then
    echo "!!  Web app not found. On the Web tab: Add a new web app -> Manual configuration ->"
    echo "!!  Python ${PYTHON#python}, then run this command again."
    exit 1
fi
SITE="$(basename "${WSGI_FILES[0]}" _wsgi.py | tr _ .)"
HOSTS="$SITE,$HOSTS"
ORIGINS="https://$SITE,$ORIGINS"
cat > "${WSGI_FILES[0]}" <<WSGI
import os
import sys
from pathlib import Path

path = "$APP_DIR"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
os.environ["DJANGO_DEBUG"] = "0"
os.environ["DJANGO_SECRET_KEY"] = Path(path, ".secret_key").read_text().strip()
os.environ["DJANGO_ALLOWED_HOSTS"] = "$HOSTS"
os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"] = "$ORIGINS"

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
WSGI
echo "    written ${WSGI_FILES[0]}"

echo "==> 6/6 Done."
echo
echo "Last step on the Web tab:"
echo "  * Virtualenv:  $APP_DIR/.venv"
echo "  * Press the green Reload button"
echo "Then open https://$SITE/"
