"""메인 페이지 라우트."""

from flask import Blueprint, render_template, redirect, url_for, g

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """랜딩 페이지 또는 생성 페이지로 리다이렉트."""
    if g.user:
        return redirect(url_for("generate.generate_page"))
    return render_template("index.html")
