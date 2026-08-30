"""进程内 TTL 缓存、交易日历感知新鲜度与统一 meta 构造（market 包共享）。

新鲜度规则（_is_fresh）：
- TTL 内：新鲜。
- TTL 外：若缓存写入时刻已覆盖「最近已完成交易日的收盘」，且当前不在
  数据变化窗口（交易日 09:15–21:00 之外：盘前/夜间/非交易日），也视为
  新鲜——周末与节假日不再触发上游重拉，数据本就不会变。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, time as dt_time, timedelta
from decimal import InvalidOperation

import pandas as pd

_cache = {}
_calendar_memo = {'close': None, 'at': 0.0}


def _calendar_enabled():
    """manage.py test 进程不做日历判断（避免测试触网，保持确定性）。"""
    return 'test' not in [a.lower() for a in sys.argv]


def _cache_get(key, ttl):
    item = _cache.get(key)
    if not item:
        return None
    if not _is_fresh(item['ts'], ttl):
        return None
    return item['data']


def _cache_set(key, data):
    _cache[key] = {'ts': time.time(), 'data': data}


def _stale_or(key, default):
    item = _cache.get(key)
    return item['data'] if item else default


def _last_session_close():
    """最近已完成交易日的 15:00（本地时区）；日历不可用时返回 None。

    结果记忆 60 秒；最多回看 20 天以覆盖春节/国庆等长假。
    """
    from django.utils import timezone
    from ..services import is_trading_day

    now = timezone.localtime()
    if now.timestamp() - _calendar_memo['at'] < 60:
        return _calendar_memo['close']
    close = None
    day = now.date()
    try:
        for _ in range(20):
            if is_trading_day(day):
                candidate = timezone.make_aware(datetime.combine(day, dt_time(15, 0)))
                if candidate <= now:
                    close = candidate
                    break
            day -= timedelta(days=1)
    except Exception:
        close = None
    _calendar_memo['close'] = close
    _calendar_memo['at'] = now.timestamp()
    return close


def _data_changing_now(now):
    """交易日 09:15–21:00 数据仍可能变化（盘中 + 收盘后晚到），沿用 TTL。"""
    from ..services import is_trading_day

    if not is_trading_day(now.date()):
        return False
    return dt_time(9, 15) <= now.time() <= dt_time(21, 0)


def _is_fresh(ts, ttl):
    if time.time() - ts <= ttl:
        return True
    if not _calendar_enabled():
        return False
    try:
        from django.utils import timezone

        if _data_changing_now(timezone.localtime()):
            return False
        close = _last_session_close()
        return close is not None and ts >= close.timestamp()
    except Exception:
        return False


def _cache_meta(cache_key, ttl, source, available, source_data_date=None, disclaimer=''):
    """统一市场 API 元数据；缓存状态只使用 fresh/stale/unavailable。"""
    item = _cache.get(cache_key)
    if not item:
        cache_status = 'unavailable'
        fetched_at = None
    else:
        cache_status = 'fresh' if _is_fresh(item['ts'], ttl) else 'stale'
        fetched_at = datetime.fromtimestamp(item['ts']).astimezone().isoformat(timespec='seconds')

    data_as_of = None
    if _calendar_enabled():
        try:
            close = _last_session_close()
            data_as_of = close.date().isoformat() if close else None
        except Exception:
            data_as_of = None

    return {
        'available': bool(available),
        'source': source,
        'source_data_date': source_data_date or None,
        'data_as_of': data_as_of,
        'fetched_at': fetched_at,
        'cache_status': cache_status,
        'disclaimer': disclaimer,
    }


def _to_float(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _now_str():
    return time.strftime('%Y-%m-%d %H:%M:%S')
