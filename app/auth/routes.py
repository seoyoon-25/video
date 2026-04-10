"""인증 라우트 — 로그인, 회원가입, 로그아웃."""

import re
import bcrypt
from functools import wraps
from urllib.parse import urlparse, urljoin
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, g, current_app
)

from ..models import (
    create_user, get_user_by_email, get_user_by_oauth
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def is_safe_url(target: str) -> bool:
    """Open Redirect 방지: 내부 URL인지 검증."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def validate_password_complexity(password: str) -> tuple[bool, str]:
    """비밀번호 복잡도 검증: 8자 이상, 영문자+숫자 필수."""
    if len(password) < 8:
        return False, "비밀번호는 최소 8자 이상이어야 합니다."
    if not re.search(r"[a-zA-Z]", password):
        return False, "비밀번호에 영문자가 포함되어야 합니다."
    if not re.search(r"[0-9]", password):
        return False, "비밀번호에 숫자가 포함되어야 합니다."
    return True, ""


def login_required(f):
    """로그인 필수 데코레이터."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.user is None:
            flash("로그인이 필요합니다.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def hash_password(password: str) -> str:
    """비밀번호 bcrypt 해싱."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password: str, hashed: str) -> bool:
    """비밀번호 검증."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """로그인 페이지."""
    if g.user:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        # Rate Limiting 적용 (5회/분)
        limiter = current_app.limiter
        limiter.limit("5 per minute")(lambda: None)()

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("이메일과 비밀번호를 입력해주세요.", "error")
            return render_template("auth/login.html")

        user = get_user_by_email(email)
        if not user:
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("auth/login.html")

        if not user["password_hash"]:
            flash("Google 계정으로 가입된 사용자입니다. Google 로그인을 이용해주세요.", "error")
            return render_template("auth/login.html")

        if not check_password(password, user["password_hash"]):
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("auth/login.html")

        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True

        # Open Redirect 방지
        next_page = request.args.get("next")
        if next_page and not is_safe_url(next_page):
            next_page = None
        return redirect(next_page or url_for("main.index"))

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """회원가입 페이지."""
    if g.user:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        # Rate Limiting 적용 (3회/분)
        limiter = current_app.limiter
        limiter.limit("3 per minute")(lambda: None)()

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        display_name = request.form.get("display_name", "").strip()

        errors = []

        if not email or "@" not in email:
            errors.append("유효한 이메일 주소를 입력해주세요.")

        # 비밀번호 복잡도 검증
        is_valid, error_msg = validate_password_complexity(password)
        if not is_valid:
            errors.append(error_msg)

        if password != password_confirm:
            errors.append("비밀번호가 일치하지 않습니다.")

        if get_user_by_email(email):
            errors.append("이미 가입된 이메일입니다.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth/register.html", email=email, display_name=display_name)

        password_hash = hash_password(password)
        user_id = create_user(
            email=email,
            password_hash=password_hash,
            display_name=display_name or email.split("@")[0],
        )

        session.clear()
        session["user_id"] = user_id
        session.permanent = True

        flash("회원가입이 완료되었습니다!", "success")
        return redirect(url_for("main.index"))

    return render_template("auth/register.html")


@auth_bp.route("/logout")
def logout():
    """로그아웃."""
    session.clear()
    flash("로그아웃되었습니다.", "info")
    return redirect(url_for("main.index"))


# ─────────────────────────────────────────────────────
# Google OAuth
# ─────────────────────────────────────────────────────

@auth_bp.route("/google")
def google_login():
    """Google OAuth 로그인 시작."""
    from .oauth import get_google_auth_url
    try:
        auth_url = get_google_auth_url()
        return redirect(auth_url)
    except Exception as e:
        flash("Google 로그인 설정을 확인해주세요.", "error")
        return redirect(url_for("auth.login"))


@auth_bp.route("/google/callback")
def google_callback():
    """Google OAuth 콜백."""
    from .oauth import handle_google_callback, verify_oauth_state

    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        flash("Google 인증에 실패했습니다.", "error")
        return redirect(url_for("auth.login"))

    # OAuth state 검증 (CSRF 방지)
    if not state or not verify_oauth_state(state):
        flash("인증 요청이 유효하지 않습니다. 다시 시도해주세요.", "error")
        return redirect(url_for("auth.login"))

    try:
        user_info = handle_google_callback(code)

        user = get_user_by_oauth("google", user_info["id"])
        if not user:
            existing = get_user_by_email(user_info["email"])
            if existing:
                flash("이미 이메일로 가입된 계정입니다. 이메일로 로그인해주세요.", "error")
                return redirect(url_for("auth.login"))

            user_id = create_user(
                email=user_info["email"],
                oauth_provider="google",
                oauth_id=user_info["id"],
                display_name=user_info.get("name", user_info["email"].split("@")[0]),
            )
        else:
            user_id = user["id"]

        session.clear()
        session["user_id"] = user_id
        session.permanent = True

        return redirect(url_for("main.index"))

    except Exception as e:
        flash("Google 인증 처리 중 오류가 발생했습니다.", "error")
        return redirect(url_for("auth.login"))
