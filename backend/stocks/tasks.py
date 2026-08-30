"""
进程内后台拉取任务（daemon thread）。

适合单机 1H2G、不引入 Celery。Gunicorn 多 worker 时状态不共享——
前端轮询应打到同一 worker 或接受「某次请求看不到 running」后重试；
本实现以「触发后的短时轮询 + 看板刷新」为主，足够个人自选规模。
"""

import logging
import threading

from django.utils import timezone

logger = logging.getLogger(__name__)

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


def get_fetch_status():
    with _lock:
        return dict(_state)


def _set(**kwargs):
    with _lock:
        _state.update(kwargs)


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
    """启动单只后台拉取。默认 light。若已有任务在跑则返回 False。"""
    with _lock:
        if _state['running']:
            return False, dict(_state)
        _state['running'] = True
        _state['last_status'] = 'running'
        snapshot = dict(_state)

    t = threading.Thread(target=_run_one, args=(stock_id, light), daemon=True)
    t.start()
    return True, snapshot


def start_fetch_all(light=True):
    """启动全部后台拉取。默认 light，减少突发大量请求。"""
    with _lock:
        if _state['running']:
            return False, dict(_state)
        _state['running'] = True
        _state['last_status'] = 'running'
        snapshot = dict(_state)

    t = threading.Thread(target=_run_all, args=(light,), daemon=True)
    t.start()
    return True, snapshot
