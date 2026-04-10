"""대시보드 라우트."""

from flask import Blueprint, render_template, g, current_app, send_file
from pathlib import Path

from ..auth.routes import login_required
from ..models import get_user_generations, get_daily_usage, can_generate

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/")
@login_required
def dashboard():
    """사용자 대시보드."""
    generations = get_user_generations(g.user["id"], limit=20)
    used_today = get_daily_usage(g.user["id"])

    daily_limit = (
        current_app.config["PREMIUM_DAILY_LIMIT"]
        if g.user["tier"] == "premium"
        else current_app.config["FREE_DAILY_LIMIT"]
    )

    can_gen, remaining = can_generate(g.user["id"], g.user["tier"])

    return render_template(
        "dashboard.html",
        generations=generations,
        used_today=used_today,
        daily_limit=daily_limit,
        remaining=remaining,
    )


@dashboard_bp.route("/download/<job_id>")
@login_required
def download_video(job_id: str):
    """비디오 다운로드."""
    from ..models import get_generation_by_job_id

    gen = get_generation_by_job_id(job_id)
    if not gen or gen["user_id"] != g.user["id"]:
        return {"error": "비디오를 찾을 수 없습니다."}, 404

    if not gen["video_path"]:
        return {"error": "비디오가 아직 생성되지 않았습니다."}, 404

    video_path = Path(gen["video_path"])
    if not video_path.exists():
        return {"error": "비디오 파일을 찾을 수 없습니다."}, 404

    return send_file(
        video_path,
        as_attachment=True,
        download_name=f"video_{job_id}.mp4",
    )
