"""进程内 TTL 缓存、统一 meta 构造与小工具（供 market 包各模块共享）。"""

from __future__ import annotations

import time
from datetime import datetime
from decimal import InvalidOperation

import pandas as pd

_cache = {}


def _cache_get(key, ttl):
    item = _cache.get(key)
    if not item:
        return None
    if time.time() - item['ts'] > ttl:
        return None
    return item['data']


def _cache_set(key, data):
    _cache[key] = {'ts': time.time(), 'data': data}


def _stale_or(key, default):
    item = _cache.get(key)
    return item['data'] if item else default


def _cache_meta(cache_key, ttl, source, available, source_data_date=None, disclaimer=''):
    """统一市场 API 元数据；缓存状态只使用 fresh/stale/unavailable。"""
    item = _cache.get(cache_key)
    if not item:
        cache_status = 'unavailable'
        fetched_at = None
    else:
        cache_status = 'fresh' if time.time() - item['ts'] <= ttl else 'stale'
        fetched_at = datetime.fromtimestamp(item['ts']).astimezone().isoformat(timespec='seconds')
    return {
        'available': bool(available),
        'source': source,
        'source_data_date': source_data_date or None,
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
