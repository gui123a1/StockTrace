"""
APScheduler 集成到 Django

在 Django 启动时自动注册定时任务：
1. 开盘前 08:50 增量日线（预热，避免手动时补大段）
2. 盘中每5分钟更新分钟数据
3. 收盘后 15:10 汇总当日日线+分钟（自选库最后一次自动写入）
4. 收盘后 15:30–21:00 每30分钟预热晚到行情缓存（交易日）

多 worker（Gunicorn）下用文件锁保证仅一个进程持有调度器。
"""

import atexit
import logging
import os
import sys
from datetime import time as dt_time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

scheduler = None
_lock_fh = None

_SKIP_COMMANDS = {
    'migrate', 'makemigrations', 'showmigrations', 'sqlmigrate',
    'collectstatic', 'shell', 'dbshell', 'test', 'check',
    'createsuperuser', 'changepassword', 'flush', 'loaddata',
    'dumpdata', 'inspectdb',
}

# 收盘后降频窗口（含端点）；用于挡住 cron 在 15:00 的误触发
_POST_CLOSE_START = dt_time(15, 30)
_POST_CLOSE_END = dt_time(21, 0)


def _should_start_scheduler():
    if os.environ.get('STOCKTRACE_SCHEDULER', '1').lower() in ('0', 'false', 'no', 'off'):
        return False

    argv = [a.lower() for a in sys.argv]
    for cmd in _SKIP_COMMANDS:
        if cmd in argv:
            return False

    # Django runserver reloader: only the child process has RUN_MAIN=true
    if 'runserver' in argv and os.environ.get('RUN_MAIN') != 'true':
        return False

    return True


def _acquire_lock():
    """Cross-platform exclusive lock; returns True if this process owns the scheduler."""
    global _lock_fh
    lock_path = os.path.join(settings.BASE_DIR, 'scheduler.lock')
    try:
        _lock_fh = open(lock_path, 'a+')
        if sys.platform == 'win32':
            import msvcrt
            _lock_fh.seek(0)
            try:
                msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                _lock_fh.close()
                _lock_fh = None
                return False
        else:
            import fcntl
            try:
                fcntl.flock(_lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                _lock_fh.close()
                _lock_fh = None
                return False
        _lock_fh.seek(0)
        _lock_fh.truncate()
        _lock_fh.write(str(os.getpid()))
        _lock_fh.flush()
        return True
    except Exception as e:
        logger.warning(f"调度文件锁获取失败: {e}")
        if _lock_fh is not None:
            try:
                _lock_fh.close()
            except Exception:
                pass
            _lock_fh = None
        return False


def _release_lock():
    global _lock_fh
    if _lock_fh is None:
        return
    try:
        if sys.platform == 'win32':
            import msvcrt
            _lock_fh.seek(0)
            try:
                msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            fcntl.flock(_lock_fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        _lock_fh.close()
    except Exception:
        pass
    _lock_fh = None


def _intraday_job():
    from .services import fetch_intraday_update
    fetch_intraday_update()


def _daily_summary_job():
    from .services import fetch_daily_summary
    fetch_daily_summary()


def _preopen_incremental_job():
    """开盘前只补日线缺口，压力小。"""
    from .services import fetch_incremental_daily_all, is_trading_day
    if not is_trading_day():
        logger.debug("非交易日，跳过开盘前增量日线")
        return
    fetch_incremental_daily_all()


def _post_close_lagging_job():
    """
    收盘后降频：仅预热可能晚到的行情缓存（北向/大盘资金/ETF 份额）。
    交易日 + [15:30, 21:00]；21:00 为当天最后一次。
    """
    from .market import warm_post_close_lagging
    from .services import is_trading_day

    if not is_trading_day():
        logger.debug("非交易日，跳过收盘后晚到数据预热")
        return

    now = timezone.localtime()
    t = now.time().replace(second=0, microsecond=0)
    if t < _POST_CLOSE_START or t > _POST_CLOSE_END:
        logger.debug("不在收盘后降频窗口 [15:30, 21:00]，跳过")
        return

    warm_post_close_lagging()


def start():
    """启动 APScheduler（带启动条件与单实例文件锁）"""
    global scheduler
    if scheduler is not None:
        return

    if not _should_start_scheduler():
        logger.debug("跳过 APScheduler 启动（命令或环境禁用）")
        return

    if not _acquire_lock():
        logger.info("APScheduler 未启动：其他进程已持有调度锁")
        return

    scheduler = BackgroundScheduler()

    # 开盘前：增量日线预热
    scheduler.add_job(
        _preopen_incremental_job,
        CronTrigger(hour=8, minute=50),
        id='preopen_incremental',
        replace_existing=True,
    )

    scheduler.add_job(
        _intraday_job,
        CronTrigger(hour='9-14', minute='*/5'),
        id='intraday_fetch',
        replace_existing=True,
    )

    scheduler.add_job(
        _daily_summary_job,
        CronTrigger(hour=15, minute=10),
        id='daily_summary',
        replace_existing=True,
    )

    # 收盘后：15:30–21:00 每 30 分钟预热晚到行情（cron 含 15:00，由窗口守卫丢弃）
    scheduler.add_job(
        _post_close_lagging_job,
        CronTrigger(
            day_of_week='mon-fri',
            hour='15,16,17,18,19,20,21',
            minute='0,30',
        ),
        id='post_close_lagging',
        replace_existing=True,
    )

    scheduler.start()
    atexit.register(stop)
    logger.info(
        "APScheduler 已启动 "
        "(08:50 增量日线 / 09-14 */5 分钟 / 15:10 收盘汇总 / "
        "15:30-21:00 */30 晚到行情预热)"
    )


def stop():
    global scheduler
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
        scheduler = None
    _release_lock()
