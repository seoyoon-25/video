"""스케줄 관리 라우트."""

import re
from flask import Blueprint, render_template, request, g, jsonify, current_app

from ..auth.routes import login_required
from ..models import (
    create_schedule, get_schedule_by_id, get_user_schedules,
    update_schedule, delete_schedule, get_schedule_history
)
from ..scheduler import add_schedule_job, remove_schedule_job, run_scheduled_job, get_scheduler_status
from ..services.voice_service import get_available_voices

schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedules")

# 허용된 플랫폼 목록
ALLOWED_PLATFORMS = {
    "shorts", "tiktok", "reels",
    "youtube_5min", "youtube_10min", "youtube_15min", "youtube_25min"
}


def get_niche_choices():
    """사용 가능한 니치 목록을 가져옵니다."""
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from verticals.niche import list_niches, load_niche

    niches = list_niches()
    choices = []
    for n in niches:
        profile = load_niche(n)
        choices.append({
            "id": n,
            "name": profile.get("display_name", n),
            "description": profile.get("description", ""),
        })
    return choices


def get_allowed_niches() -> set:
    """허용된 니치 목록을 가져옵니다."""
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from verticals.niche import list_niches
    return set(list_niches())


def validate_niche_platform(niche: str, platform: str) -> tuple[bool, str]:
    """niche와 platform이 허용된 값인지 검증."""
    allowed_niches = get_allowed_niches()
    if niche not in allowed_niches:
        return False, f"허용되지 않는 니치입니다: {niche}"
    if platform not in ALLOWED_PLATFORMS:
        return False, f"허용되지 않는 플랫폼입니다: {platform}"
    return True, ""


def validate_time_format(time_str: str) -> bool:
    """HH:MM 형식 검증."""
    if not time_str:
        return False
    pattern = r'^([01]?[0-9]|2[0-3]):([0-5][0-9])$'
    return bool(re.match(pattern, time_str))


@schedule_bp.route("/")
@login_required
def schedule_list():
    """스케줄 관리 페이지."""
    schedules = get_user_schedules(g.user["id"])
    niches = get_niche_choices()
    voices = get_available_voices()

    return render_template(
        "schedule.html",
        schedules=schedules,
        niches=niches,
        voices=voices,
    )


@schedule_bp.route("/api")
@login_required
def api_list_schedules():
    """스케줄 목록 API."""
    schedules = get_user_schedules(g.user["id"])
    return jsonify({"schedules": schedules})


@schedule_bp.route("/api", methods=["POST"])
@login_required
def api_create_schedule():
    """스케줄 생성 API."""
    data = request.get_json() or request.form

    name = data.get("name", "").strip()
    schedule_time = data.get("schedule_time", "").strip()
    niche = data.get("niche", "general")
    platform = data.get("platform", "shorts")
    voice_id = data.get("voice_id", "")
    topic_source = data.get("topic_source", "auto")
    manual_topic = data.get("manual_topic", "").strip()

    if not name:
        return jsonify({"error": "스케줄 이름을 입력해주세요."}), 400

    if not validate_time_format(schedule_time):
        return jsonify({"error": "올바른 시간 형식을 입력해주세요. (HH:MM)"}), 400

    if topic_source == "manual" and not manual_topic:
        return jsonify({"error": "수동 토픽을 입력해주세요."}), 400

    # 입력값 검증
    is_valid, error_msg = validate_niche_platform(niche, platform)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    schedule_id = create_schedule(
        user_id=g.user["id"],
        name=name,
        schedule_time=schedule_time,
        niche=niche,
        platform=platform,
        voice_id=voice_id,
        topic_source=topic_source,
        manual_topic=manual_topic,
    )

    # 스케줄러에 작업 등록
    schedule = get_schedule_by_id(schedule_id)
    add_schedule_job(current_app._get_current_object(), dict(schedule))

    return jsonify({
        "success": True,
        "schedule_id": schedule_id,
        "message": "스케줄이 생성되었습니다.",
    })


@schedule_bp.route("/api/<int:schedule_id>", methods=["GET"])
@login_required
def api_get_schedule(schedule_id: int):
    """스케줄 상세 조회 API."""
    schedule = get_schedule_by_id(schedule_id)
    if not schedule or schedule["user_id"] != g.user["id"]:
        return jsonify({"error": "스케줄을 찾을 수 없습니다."}), 404

    history = get_schedule_history(schedule_id, limit=10)

    return jsonify({
        "schedule": dict(schedule),
        "history": history,
    })


@schedule_bp.route("/api/<int:schedule_id>", methods=["PUT"])
@login_required
def api_update_schedule(schedule_id: int):
    """스케줄 수정 API."""
    schedule = get_schedule_by_id(schedule_id)
    if not schedule or schedule["user_id"] != g.user["id"]:
        return jsonify({"error": "스케줄을 찾을 수 없습니다."}), 404

    data = request.get_json() or request.form

    name = data.get("name")
    schedule_time = data.get("schedule_time")
    niche = data.get("niche")
    platform = data.get("platform")
    voice_id = data.get("voice_id")
    topic_source = data.get("topic_source")
    manual_topic = data.get("manual_topic")
    enabled = data.get("enabled")

    if schedule_time and not validate_time_format(schedule_time):
        return jsonify({"error": "올바른 시간 형식을 입력해주세요. (HH:MM)"}), 400

    # 입력값 검증 (값이 제공된 경우에만)
    if niche is not None or platform is not None:
        check_niche = niche if niche is not None else schedule["niche"]
        check_platform = platform if platform is not None else schedule["platform"]
        is_valid, error_msg = validate_niche_platform(check_niche, check_platform)
        if not is_valid:
            return jsonify({"error": error_msg}), 400

    if enabled is not None:
        enabled = 1 if enabled in (True, 1, "1", "true") else 0

    update_schedule(
        schedule_id,
        name=name,
        niche=niche,
        platform=platform,
        voice_id=voice_id,
        topic_source=topic_source,
        manual_topic=manual_topic,
        schedule_time=schedule_time,
        enabled=enabled,
    )

    # 스케줄러 작업 업데이트
    updated_schedule = get_schedule_by_id(schedule_id)
    if updated_schedule["enabled"]:
        add_schedule_job(current_app._get_current_object(), dict(updated_schedule))
    else:
        remove_schedule_job(schedule_id)

    return jsonify({
        "success": True,
        "message": "스케줄이 수정되었습니다.",
    })


@schedule_bp.route("/api/<int:schedule_id>", methods=["DELETE"])
@login_required
def api_delete_schedule(schedule_id: int):
    """스케줄 삭제 API."""
    schedule = get_schedule_by_id(schedule_id)
    if not schedule or schedule["user_id"] != g.user["id"]:
        return jsonify({"error": "스케줄을 찾을 수 없습니다."}), 404

    # 스케줄러에서 작업 제거
    remove_schedule_job(schedule_id)

    delete_schedule(schedule_id)

    return jsonify({
        "success": True,
        "message": "스케줄이 삭제되었습니다.",
    })


@schedule_bp.route("/api/<int:schedule_id>/run", methods=["POST"])
@login_required
def api_run_schedule(schedule_id: int):
    """스케줄 즉시 실행 API."""
    schedule = get_schedule_by_id(schedule_id)
    if not schedule or schedule["user_id"] != g.user["id"]:
        return jsonify({"error": "스케줄을 찾을 수 없습니다."}), 404

    # 백그라운드에서 실행
    from threading import Thread

    def run_in_background():
        with current_app.app_context():
            run_scheduled_job(current_app._get_current_object(), schedule_id)

    thread = Thread(target=run_in_background)
    thread.daemon = True
    thread.start()

    return jsonify({
        "success": True,
        "message": "스케줄 실행이 시작되었습니다. 완료되면 대시보드에서 확인할 수 있습니다.",
    })


@schedule_bp.route("/api/<int:schedule_id>/toggle", methods=["POST"])
@login_required
def api_toggle_schedule(schedule_id: int):
    """스케줄 활성화/비활성화 토글 API."""
    schedule = get_schedule_by_id(schedule_id)
    if not schedule or schedule["user_id"] != g.user["id"]:
        return jsonify({"error": "스케줄을 찾을 수 없습니다."}), 404

    new_enabled = 0 if schedule["enabled"] else 1
    update_schedule(schedule_id, enabled=new_enabled)

    # 스케줄러 작업 업데이트
    if new_enabled:
        updated_schedule = get_schedule_by_id(schedule_id)
        add_schedule_job(current_app._get_current_object(), dict(updated_schedule))
    else:
        remove_schedule_job(schedule_id)

    return jsonify({
        "success": True,
        "enabled": bool(new_enabled),
        "message": "활성화됨" if new_enabled else "비활성화됨",
    })


@schedule_bp.route("/status")
@login_required
def scheduler_status():
    """스케줄러 상태 조회."""
    status = get_scheduler_status()
    return jsonify(status)
