"""
进程内后台拉取任务（daemon thread）。

适合单机 1H2G、不引入 Celery。Gunicorn 多 worker 时状态不共享——
前端轮询应打到同一 worker 或接受「某次请求看不到 running」后重试；
本实现以「触发后的短时轮询 + 看板刷新」为主，足够个人自选规模。
"""

import logging
import threading
import time

from django.utils import timezone

logger = logging.getLogger(__name__)

# 看门狗阈值（秒）：running 超过该时长视为线程挂死（上游无响应等），允许新任务接管。
# 正常全量 light 数分钟内完成；触发阈值即说明异常，而非任务本身耗时。
_STALE_AFTER_SECONDS = {'one': 10 * 60, 'all': 30 * 60}

_lock = threading.Lock()
_state = {
    'running': False,
    'task': None,  # 'one' | 'all' | None
    'code': None,
    'last_started': None,
    'last_finished': None,
    'last_error': None,
    'last_results': None,
    'last_status': 'idle',  # idle | running | success | error
}
_started_at = None  # time.monotonic() 秒，配合 running 判断是否挂死


def get_fetch_status():
    with _lock:
        status = dict(_state)
        if status['running'] and _started_at is not None:
            status['running_seconds'] = int(time.monotonic() - _started_at)
        return status


def _set(**kwargs):
    with _lock:
        _state.update(kwargs)


def _mark_started():
    global _started_at
    _started_at = time.monotonic()


def _fail_locked(message):
    """复位为 error 终态。调用方需已持有 _lock。"""
    global _started_at
    _state.update(
        running=False,
        last_finished=timezone.now().isoformat(),
        last_error=message,
        last_status='error',
        task=None,
    )
    _started_at = None


def _recover_stale_locked():
    """running 超过阈值视为线程挂死，看门狗接管复位。调用方需已持有 _lock。"""
    if not _state['running'] or _started_at is None:
        return
    limit = _STALE_AFTER_SECONDS.get(_state['task'], _STALE_AFTER_SECONDS['all'])
    elapsed = time.monotonic() - _started_at
    if elapsed <= limit:
        return
    logger.warning(
        "拉取任务 %s 已运行 %d 秒（阈值 %d 秒），疑似挂死，看门狗接管",
        _state['task'], int(elapsed), limit,
    )
    _fail_locked(f'任务运行 {int(elapsed)} 秒未结束，已被看门狗接管')


def _run_one(stock_id, light=False):
    from .models import Stock
    from .services import fetch_stock_all_data

    try:
        stock = Stock.objects.get(pk=stock_id)
        _set(
            running=True,
            task='one',
            code=stock.code,
            last_started=timezone.now().isoformat(),
            last_finished=None,
            last_error=None,
            last_status='running',
        )
        _mark_started()
        count = fetch_stock_all_data(stock, light=light)
        _set(
            running=False,
            last_finished=timezone.now().isoformat(),
            last_results={'code': stock.code, 'count': count},
            last_status='success',
            task=None,
        )
    except Exception as e:
        logger.exception(f"后台拉取股票 {stock_id} 失败")
        _set(
            running=False,
            last_finished=timezone.now().isoformat(),
            last_error=str(e),
            last_status='error',
            task=None,
        )


def _run_all(light=False):
    from .services import fetch_all_active_stocks

    try:
        _set(
            running=True,
            task='all',
            code=None,
            last_started=timezone.now().isoformat(),
            last_finished=None,
            last_error=None,
            last_status='running',
        )
        _mark_started()
        results = fetch_all_active_stocks(light=light)
        _set(
            running=False,
            last_finished=timezone.now().isoformat(),
            last_results=results,
            last_status='success',
            task=None,
        )
    except Exception as e:
        logger.exception("后台拉取全部股票失败")
        _set(
            running=False,
            last_finished=timezone.now().isoformat(),
            last_error=str(e),
            last_status='error',
            task=None,
        )


def start_fetch_one(stock_id, light=True):
    """启动单只后台拉取。默认 light。若已有任务在跑则返回 False（挂死任务由看门狗接管）。"""
    with _lock:
        _recover_stale_locked()
        if _state['running']:
            return False, dict(_state)
        _state['running'] = True
        _state['last_status'] = 'running'
        _mark_started()
        snapshot = dict(_state)

    t = threading.Thread(target=_run_one, args=(stock_id, light), daemon=True)
    t.start()
    return True, snapshot


def start_fetch_all(light=True):
    """启动全部后台拉取。默认 light，减少突发大量请求（挂死任务由看门狗接管）。"""
    with _lock:
        _recover_stale_locked()
        if _state['running']:
            return False, dict(_state)
        _state['running'] = True
        _state['last_status'] = 'running'
        _mark_started()
        snapshot = dict(_state)

    t = threading.Thread(target=_run_all, args=(light,), daemon=True)
    t.start()
    return True, snapshot
