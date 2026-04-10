"""SQLite3 데이터베이스 모델 및 유틸리티."""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from flask import g, current_app


def get_db() -> sqlite3.Connection:
    """현재 요청에 대한 데이터베이스 연결을 반환."""
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(str(db_path))
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """데이터베이스 연결 종료."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """데이터베이스 테이블 초기화."""
    db = get_db()

    # 1단계: 기본 테이블 생성 (인덱스 제외)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            oauth_provider TEXT,
            oauth_id TEXT,
            display_name TEXT,
            tier TEXT DEFAULT 'free',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_id TEXT UNIQUE,
            topic TEXT,
            niche TEXT,
            platform TEXT,
            voice_id TEXT,
            status TEXT DEFAULT 'pending',
            video_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS daily_usage (
            user_id INTEGER NOT NULL,
            date DATE NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            niche TEXT DEFAULT 'general',
            platform TEXT DEFAULT 'shorts',
            voice_id TEXT,
            topic_source TEXT DEFAULT 'auto',
            manual_topic TEXT,
            schedule_time TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            last_run_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    db.commit()

    # 2단계: 기존 테이블에 새 컬럼 추가 (마이그레이션)
    _migrate_generations_table(db)

    # 3단계: 인덱스 생성 (마이그레이션 후)
    db.executescript("""
        CREATE INDEX IF NOT EXISTS idx_generations_user_id ON generations(user_id);
        CREATE INDEX IF NOT EXISTS idx_generations_job_id ON generations(job_id);
        CREATE INDEX IF NOT EXISTS idx_generations_schedule_id ON generations(schedule_id);
        CREATE INDEX IF NOT EXISTS idx_daily_usage_date ON daily_usage(date);
        CREATE INDEX IF NOT EXISTS idx_schedules_user_id ON schedules(user_id);
        CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled);
    """)
    db.commit()


def _migrate_generations_table(db):
    """generations 테이블에 새 컬럼 추가 (마이그레이션)."""
    cursor = db.execute("PRAGMA table_info(generations)")
    columns = {row[1] for row in cursor.fetchall()}

    if "step" not in columns:
        db.execute("ALTER TABLE generations ADD COLUMN step TEXT DEFAULT 'completed'")
    if "script_data" not in columns:
        db.execute("ALTER TABLE generations ADD COLUMN script_data TEXT")
    if "schedule_id" not in columns:
        db.execute("ALTER TABLE generations ADD COLUMN schedule_id INTEGER")
    db.commit()


def init_app(app):
    """Flask 앱에 데이터베이스 연결."""
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


# ─────────────────────────────────────────────────────
# 사용자 관련 함수
# ─────────────────────────────────────────────────────

def create_user(
    email: str,
    password_hash: Optional[str] = None,
    oauth_provider: Optional[str] = None,
    oauth_id: Optional[str] = None,
    display_name: Optional[str] = None,
) -> int:
    """새 사용자 생성, 사용자 ID 반환."""
    db = get_db()
    cursor = db.execute(
        """INSERT INTO users (email, password_hash, oauth_provider, oauth_id, display_name)
           VALUES (?, ?, ?, ?, ?)""",
        (email, password_hash, oauth_provider, oauth_id, display_name or email.split("@")[0]),
    )
    db.commit()
    return cursor.lastrowid


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    """이메일로 사용자 조회."""
    db = get_db()
    return db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    """ID로 사용자 조회."""
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_oauth(provider: str, oauth_id: str) -> Optional[sqlite3.Row]:
    """OAuth 정보로 사용자 조회."""
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE oauth_provider = ? AND oauth_id = ?",
        (provider, oauth_id),
    ).fetchone()


# ─────────────────────────────────────────────────────
# 생성 이력 관련 함수
# ─────────────────────────────────────────────────────

def create_generation(
    user_id: int,
    job_id: str,
    topic: str,
    niche: str,
    platform: str,
    voice_id: str = "",
) -> int:
    """새 생성 작업 기록."""
    db = get_db()
    cursor = db.execute(
        """INSERT INTO generations (user_id, job_id, topic, niche, platform, voice_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, job_id, topic, niche, platform, voice_id),
    )
    db.commit()
    return cursor.lastrowid


def update_generation_status(job_id: str, status: str, video_path: str = None):
    """생성 작업 상태 업데이트."""
    db = get_db()
    if video_path:
        db.execute(
            "UPDATE generations SET status = ?, video_path = ? WHERE job_id = ?",
            (status, video_path, job_id),
        )
    else:
        db.execute(
            "UPDATE generations SET status = ? WHERE job_id = ?",
            (status, job_id),
        )
    db.commit()


def get_user_generations(user_id: int, limit: int = 20) -> list:
    """사용자의 생성 이력 조회."""
    db = get_db()
    rows = db.execute(
        """SELECT * FROM generations WHERE user_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_generation_by_job_id(job_id: str) -> Optional[sqlite3.Row]:
    """job_id로 생성 작업 조회."""
    db = get_db()
    return db.execute("SELECT * FROM generations WHERE job_id = ?", (job_id,)).fetchone()


# ─────────────────────────────────────────────────────
# 일일 사용량 관련 함수
# ─────────────────────────────────────────────────────

def get_daily_usage(user_id: int) -> int:
    """오늘 사용량 조회."""
    db = get_db()
    today = date.today().isoformat()
    row = db.execute(
        "SELECT count FROM daily_usage WHERE user_id = ? AND date = ?",
        (user_id, today),
    ).fetchone()
    return row["count"] if row else 0


def increment_daily_usage(user_id: int) -> int:
    """오늘 사용량 증가, 새 사용량 반환."""
    db = get_db()
    today = date.today().isoformat()

    db.execute(
        """INSERT INTO daily_usage (user_id, date, count) VALUES (?, ?, 1)
           ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1""",
        (user_id, today),
    )
    db.commit()
    return get_daily_usage(user_id)


def can_generate(user_id: int, user_tier: str = "free") -> tuple[bool, int]:
    """생성 가능 여부와 남은 횟수 확인."""
    from flask import current_app

    limit = (
        current_app.config["PREMIUM_DAILY_LIMIT"]
        if user_tier == "premium"
        else current_app.config["FREE_DAILY_LIMIT"]
    )
    used = get_daily_usage(user_id)
    remaining = max(0, limit - used)
    return remaining > 0, remaining


# ─────────────────────────────────────────────────────
# 단계별 워크플로우 관련 함수
# ─────────────────────────────────────────────────────

def update_generation_step(job_id: str, step: str, script_data: str = None):
    """생성 작업 단계 업데이트."""
    db = get_db()
    if script_data:
        db.execute(
            "UPDATE generations SET step = ?, script_data = ? WHERE job_id = ?",
            (step, script_data, job_id),
        )
    else:
        db.execute(
            "UPDATE generations SET step = ? WHERE job_id = ?",
            (step, job_id),
        )
    db.commit()


def get_generations_by_step(user_id: int, step: str, limit: int = 20) -> list:
    """특정 단계의 생성 작업 조회."""
    db = get_db()
    rows = db.execute(
        """SELECT * FROM generations WHERE user_id = ? AND step = ?
           ORDER BY created_at DESC LIMIT ?""",
        (user_id, step, limit),
    ).fetchall()
    return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────
# 스케줄 관련 함수
# ─────────────────────────────────────────────────────

def create_schedule(
    user_id: int,
    name: str,
    schedule_time: str,
    niche: str = "general",
    platform: str = "shorts",
    voice_id: str = "",
    topic_source: str = "auto",
    manual_topic: str = "",
) -> int:
    """새 스케줄 생성."""
    db = get_db()
    cursor = db.execute(
        """INSERT INTO schedules
           (user_id, name, niche, platform, voice_id, topic_source, manual_topic, schedule_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, name, niche, platform, voice_id, topic_source, manual_topic, schedule_time),
    )
    db.commit()
    return cursor.lastrowid


def get_schedule_by_id(schedule_id: int) -> Optional[sqlite3.Row]:
    """ID로 스케줄 조회."""
    db = get_db()
    return db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()


def get_user_schedules(user_id: int) -> list:
    """사용자의 모든 스케줄 조회."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM schedules WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_active_schedules() -> list:
    """활성화된 모든 스케줄 조회."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM schedules WHERE enabled = 1"
    ).fetchall()
    return [dict(row) for row in rows]


def update_schedule(
    schedule_id: int,
    name: str = None,
    niche: str = None,
    platform: str = None,
    voice_id: str = None,
    topic_source: str = None,
    manual_topic: str = None,
    schedule_time: str = None,
    enabled: int = None,
):
    """스케줄 업데이트."""
    db = get_db()
    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if niche is not None:
        updates.append("niche = ?")
        params.append(niche)
    if platform is not None:
        updates.append("platform = ?")
        params.append(platform)
    if voice_id is not None:
        updates.append("voice_id = ?")
        params.append(voice_id)
    if topic_source is not None:
        updates.append("topic_source = ?")
        params.append(topic_source)
    if manual_topic is not None:
        updates.append("manual_topic = ?")
        params.append(manual_topic)
    if schedule_time is not None:
        updates.append("schedule_time = ?")
        params.append(schedule_time)
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(enabled)

    if updates:
        params.append(schedule_id)
        db.execute(
            f"UPDATE schedules SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        db.commit()


def update_schedule_last_run(schedule_id: int):
    """스케줄 마지막 실행 시간 업데이트."""
    db = get_db()
    db.execute(
        "UPDATE schedules SET last_run_at = CURRENT_TIMESTAMP WHERE id = ?",
        (schedule_id,),
    )
    db.commit()


def delete_schedule(schedule_id: int):
    """스케줄 삭제."""
    db = get_db()
    db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    db.commit()


def get_schedule_history(schedule_id: int, limit: int = 10) -> list:
    """스케줄 실행 이력 조회."""
    db = get_db()
    rows = db.execute(
        """SELECT * FROM generations WHERE schedule_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (schedule_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
