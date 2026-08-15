#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input --settings=config.settings.production
python manage.py migrate --settings=config.settings.production
python manage.py seed_inicial --settings=config.settings.production
python manage.py seed_teste_perfis --settings=config.settings.production
python manage.py importar_materiais data/Lista_de_materiais_Engemil.xlsx --settings=config.settings.production
python manage.py seed_demo --settings=config.settings.production