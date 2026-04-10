"""Gunicorn 설정 파일."""

import multiprocessing

# 바인딩
bind = "127.0.0.1:5050"

# 워커 수 (CPU 코어 수 * 2 + 1)
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)

# 워커 클래스
worker_class = "sync"

# 타임아웃 (롱폼 생성에 시간이 오래 걸릴 수 있음)
timeout = 600

# 로깅
accesslog = "/var/www/video/logs/access.log"
errorlog = "/var/www/video/logs/error.log"
loglevel = "info"

# 프로세스 이름
proc_name = "video-bestcome"

# 데몬 모드 비활성화 (systemd가 관리)
daemon = False

# 리로드 (개발용, 프로덕션에서는 False)
reload = False
