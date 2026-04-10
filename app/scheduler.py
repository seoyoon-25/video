"""APScheduler 기반 자동 스케줄링 모듈."""

import json
import time
import logging
from pathlib import Path
from datetime import datetime
from threading import Lock

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# 전역 스케줄러 인스턴스
_scheduler = None
_scheduler_lock = Lock()


def get_scheduler() -> BackgroundScheduler:
    """전역 스케줄러 인스턴스 반환."""
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                _scheduler = BackgroundScheduler(
                    timezone="Asia/Seoul",
                    job_defaults={
                        "coalesce": True,
                        "max_instances": 1,
                        "misfire_grace_time": 3600,
                    }
                )
    return _scheduler


def run_scheduled_job(app, schedule_id: int):
    """스케줄된 비디오 생성 작업 실행."""
    with app.app_context():
        from .models import (
            get_schedule_by_id, update_schedule_last_run,
            create_generation, update_generation_status, update_generation_step
        )

        schedule = get_schedule_by_id(schedule_id)
        if not schedule:
            logger.error(f"스케줄 {schedule_id}를 찾을 수 없음")
            return

        if not schedule["enabled"]:
            logger.info(f"스케줄 {schedule_id}가 비활성화됨")
            return

        logger.info(f"스케줄 {schedule_id} 실행 시작: {schedule['name']}")

        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

            from verticals.draft import generate_draft
            from verticals.broll import generate_broll
            from verticals.tts import generate_voiceover
            from verticals.captions import generate_captions
            from verticals.assemble import assemble_video
            from verticals.niche import load_niche, get_voice_config
            from verticals.config import DRAFTS_DIR, MEDIA_DIR
            from verticals.state import PipelineState
            from verticals.topics import TopicEngine

            # 토픽 결정
            if schedule["topic_source"] == "manual" and schedule["manual_topic"]:
                topic = schedule["manual_topic"]
            else:
                # 자동 토픽 발견
                topic_engine = TopicEngine(schedule["niche"])
                topics = topic_engine.discover(limit=1)
                if topics:
                    topic = topics[0].get("title", topics[0].get("topic", ""))
                else:
                    logger.warning(f"스케줄 {schedule_id}: 토픽 발견 실패")
                    return

            job_id = str(int(time.time() * 1000))
            niche = schedule["niche"]
            platform = schedule["platform"]
            voice_id = schedule["voice_id"] or ""

            # DB 레코드 생성
            create_generation(
                user_id=schedule["user_id"],
                job_id=job_id,
                topic=topic,
                niche=niche,
                platform=platform,
                voice_id=voice_id,
            )
            update_generation_step(job_id, "draft_pending")

            # 드래프트 생성
            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            draft = generate_draft(
                topic, "",
                niche=niche,
                platform=platform,
                provider="gemini",
            )
            draft["job_id"] = job_id

            out_path = DRAFTS_DIR / f"{job_id}.json"
            state = PipelineState(draft)
            state.complete_stage("research")
            state.complete_stage("draft")
            state.save(out_path)

            script_data = json.dumps(draft, ensure_ascii=False)
            update_generation_step(job_id, "images", script_data)

            # 이미지 생성
            media_dir = MEDIA_DIR / job_id
            media_dir.mkdir(parents=True, exist_ok=True)
            profile = load_niche(niche)
            broll_prompts = draft.get("broll_prompts", [])
            generate_broll(broll_prompts, media_dir, profile)

            update_generation_step(job_id, "voice")

            # 음성 생성
            voice_config = get_voice_config(profile, "edge_tts")
            if voice_id:
                voice_config["voice_id"] = voice_id
            script_text = draft.get("script", "")
            generate_voiceover(
                script_text,
                media_dir,
                lang="ko" if any('\uAC00' <= c <= '\uD7A3' for c in script_text) else "en",
                provider="edge",
                voice_config=voice_config,
            )

            update_generation_step(job_id, "captions")

            # 자막 생성
            audio_files = list(media_dir.glob("voiceover_*.mp3"))
            if audio_files:
                generate_captions(audio_files[0], media_dir)

            update_generation_step(job_id, "assembly")

            # 영상 조립
            video_path = assemble_video(job_id, profile)

            # 완료
            update_generation_step(job_id, "completed")
            update_generation_status(job_id, "completed", str(video_path))
            update_schedule_last_run(schedule_id)

            logger.info(f"스케줄 {schedule_id} 완료: {video_path}")

            # YouTube 업로드 (선택적)
            # TODO: YouTube 업로드 기능 추가

        except Exception as e:
            logger.error(f"스케줄 {schedule_id} 실행 실패: {e}", exc_info=True)
            if 'job_id' in locals():
                update_generation_status(job_id, "failed")


def add_schedule_job(app, schedule: dict):
    """스케줄 작업 등록."""
    scheduler = get_scheduler()
    schedule_id = schedule["id"]
    job_id = f"schedule_{schedule_id}"

    # 기존 작업이 있으면 제거
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not schedule.get("enabled", True):
        logger.info(f"스케줄 {schedule_id} 비활성화됨, 작업 등록 건너뜀")
        return

    # schedule_time 파싱 (HH:MM 형식)
    try:
        schedule_time = schedule["schedule_time"]
        hour, minute = map(int, schedule_time.split(":"))
    except (ValueError, TypeError):
        logger.error(f"스케줄 {schedule_id}: 잘못된 시간 형식 '{schedule.get('schedule_time')}'")
        return

    trigger = CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul")

    scheduler.add_job(
        run_scheduled_job,
        trigger=trigger,
        id=job_id,
        args=[app, schedule_id],
        replace_existing=True,
    )

    logger.info(f"스케줄 {schedule_id} 등록: 매일 {hour:02d}:{minute:02d}")


def remove_schedule_job(schedule_id: int):
    """스케줄 작업 제거."""
    scheduler = get_scheduler()
    job_id = f"schedule_{schedule_id}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"스케줄 {schedule_id} 작업 제거됨")


def init_scheduler(app):
    """앱 시작 시 스케줄러 초기화."""
    scheduler = get_scheduler()

    # 이미 실행 중이면 건너뜀
    if scheduler.running:
        logger.info("스케줄러가 이미 실행 중")
        return

    with app.app_context():
        from .models import get_active_schedules

        schedules = get_active_schedules()
        for schedule in schedules:
            add_schedule_job(app, schedule)

    scheduler.start()
    logger.info(f"스케줄러 시작됨, 등록된 작업 수: {len(scheduler.get_jobs())}")


def shutdown_scheduler():
    """스케줄러 종료."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("스케줄러 종료됨")


def get_scheduler_status() -> dict:
    """스케줄러 상태 조회."""
    scheduler = get_scheduler()
    jobs = scheduler.get_jobs()

    return {
        "running": scheduler.running,
        "job_count": len(jobs),
        "jobs": [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in jobs
        ]
    }
