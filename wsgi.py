"""WSGI 엔트리포인트 — Gunicorn용."""

import os
from app import create_app

# 프로덕션 환경
os.environ.setdefault("FLASK_ENV", "production")

app = create_app("production")

if __name__ == "__main__":
    app.run()
