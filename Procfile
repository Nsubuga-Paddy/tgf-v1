release: python manage.py collectstatic --noinput && python manage.py migrate
web: gunicorn mcs.wsgi:application --log-file -
