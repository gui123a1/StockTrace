"""估值快照字段源：腾讯实时行情（qt.gtimg.cn）批量取换手率/市盈率/市净率/市值。

设计：
- 自选股池规模小（≤20），一次批量请求即可；进程内缓存 300 秒；
- 上游不可用时整体返回空 map，字段取值为 None（如实未知，不当 0）；
- 腾讯口径：市盈率为 TTM（field 39），市值单位为亿（换算为元）。
"""

from __future__ import annotations

import logging

import requests

from ..market._cache import _cache_get, _cache_set
from ..services import _to_shsz_prefix

logger = logging.getLogger(__name__)

_VALUATION_TTL = 300
_REQUEST_TIMEOUT = 5

# qt.gtimg.cn 返回串按 ~ 分列（0 起）的字段位（已用 sz000001 实测核对）
_IDX_TURNOVER = 38  # 换手率 %
_IDX_PE = 39        # 市盈率 TTM
_IDX_FLOAT_MV = 44  # 流通市值（亿）
_IDX_TOTAL_MV = 45  # 总市值（亿）
_IDX_PB = 46        # 市净率


def _parse_row(parts):
    def _num(idx, scale=1.0):
        try:
            raw = parts[idx]
        except IndexError:
            return None
        if raw in ('', '-'):
            return None
        try:
            return float(raw) * scale
        except ValueError:
            return None

    return {
        'turnover_rate': _num(_IDX_TURNOVER),
        'pe_ttm': _num(_IDX_PE),
        'pb': _num(_IDX_PB),
        'float_mv': _num(_IDX_FLOAT_MV, 1e8),  # 亿 → 元
        'total_mv': _num(_IDX_TOTAL_MV, 1e8),
    }


def _fetch_raw(codes):
    symbols = ','.join(_to_shsz_prefix(c) for c in codes)
    url = f'https://qt.gtimg.cn/q={symbols}'
    resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = resp.content.decode('gbk', errors='replace')
    result = {}
    for line in text.strip().split(';'):
        line = line.strip()
        if '=' not in line:
            continue
        var, _, payload = line.partition('=')
        payload = payload.strip().strip('"')
        parts = payload.split('~')
        if len(parts) < 50:
            continue
        # v_sz000001="..." → 代码取自字段 2（上游回显，不信任变量名切分）
        code = parts[2].zfill(6)
        result[code] = _parse_row(parts)
    return result


def fetch_valuation_map(codes):
    """返回 {code: {turnover_rate, pe_ttm, pb, float_mv, total_mv}}；缺失的 code 不在 map 中。"""
    wanted = [str(c).zfill(6) for c in codes]
    if not wanted:
        return {}

    cached = _cache_get('stock_valuation', _VALUATION_TTL) or {}
    missing = [c for c in wanted if c not in cached]
    if missing:
        try:
            cached.update(_fetch_raw(missing))
            _cache_set('stock_valuation', cached)
        except Exception as e:
            logger.warning(f"腾讯估值快照拉取失败（字段按 None 处理）: {e}")

    return {c: cached[c] for c in wanted if c in cached}
