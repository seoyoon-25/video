"""Flask App Factory — 비디오 생성 웹앱."""

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask

from .config import config


def create_app(config_name: str = None) -> Flask:
    """Flask 앱 팩토리."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config.get(config_name, config["default"]))

    # 프로덕션 환경에서 SECRET_KEY 필수 검증
    if config_name == "production":
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError("프로덕션 환경에서는 SECRET_KEY 환경변수가 필수입니다.")

    # CSRF 보호 초기화
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect(app)

    # Rate Limiting 초기화
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://",
    )
    app.limiter = limiter

    # instance 폴더 생성
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # 데이터베이스 초기화
    from . import models
    models.init_app(app)

    # 블루프린트 등록
    from .auth.routes import auth_bp
    from .routes.main import main_bp
    from .routes.generate import generate_bp
    from .routes.dashboard import dashboard_bp
    from .routes.api import api_bp
    from .routes.schedule import schedule_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(schedule_bp)

    # 스케줄러 초기화 (프로덕션 환경에서만)
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from .scheduler import init_scheduler
        init_scheduler(app)

    # 로그인 매니저 초기화 (자체 구현)
    @app.before_request
    def load_user():
        from flask import session, g
        user_id = session.get("user_id")
        if user_id:
            g.user = models.get_user_by_id(user_id)
        else:
            g.user = None

    # 템플릿 컨텍스트 프로세서
    @app.context_processor
    def inject_user():
        from flask import g
        return {"current_user": g.get("user")}

    # 커스텀 에러 핸들러
    from flask import render_template

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template("errors/500.html"), 500

    @app.errorhandler(429)
    def ratelimit_exceeded(e):
        return {"error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."}, 429

    # 로깅 설정 (프로덕션)
    if not app.debug:
        log_dir = os.path.join(app.instance_path, "logs")
        os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "video.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=10,
        )
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info("Flask 앱 시작됨")

    return app
