web: gunicorn app:app --workers=1
worker: rq worker -u $REDIS_URL
