"""Flask App Factory — 비디오 생성 웹앱."""

import os
from flask import Flask

from .config import config


def create_app(config_name: str = None) -> Flask:
    """Flask 앱 팩토리."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config.get(config_name, config["default"]))

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

    return app
