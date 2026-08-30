"""指数行情：主要指数现价与多指数归一化走势。"""

from __future__ import annotations

import akshare as ak
import pandas as pd

from ._cache import _cache_get, _cache_set, _stale_or, _to_float
from ._sources import _safe_df_call

MAJOR_INDICES = [
    ('sh000001', '上证指数'),
    ('sz399001', '深证成指'),
    ('sz399006', '创业板指'),
    ('sh000300', '沪深300'),
    ('sh000016', '上证50'),
    ('sh000688', '科创50'),
    ('sh000852', '中证1000'),
    ('sz399005', '中小100'),
]

# 走势图对比用（新浪日线代码）
TREND_INDICES = [
    ('sh000001', '上证指数'),
    ('sz399001', '深证成指'),
    ('sz399006', '创业板指'),
    ('sh000300', '沪深300'),
    ('sh000688', '科创50'),
]


def fetch_major_indices(ttl=60):
    cached = _cache_get('indices', ttl)
    if cached is not None:
        return cached

    df = _safe_df_call(ak.stock_zh_index_spot_sina, source_name='sina_index_spot')
    if df is None or df.empty:
        return _stale_or('indices', [])

    by_code = {str(r['代码']): r for _, r in df.iterrows()}
    result = []
    for code, fallback_name in MAJOR_INDICES:
        row = by_code.get(code)
        if row is None:
            result.append({
                'code': code,
                'name': fallback_name,
                'price': None,
                'change': None,
                'change_pct': None,
                'open': None,
                'high': None,
                'low': None,
                'prev_close': None,
                'volume': None,
                'turnover': None,
            })
            continue
        result.append({
            'code': code,
            'name': str(row.get('名称') or fallback_name),
            'price': _to_float(row.get('最新价')),
            'change': _to_float(row.get('涨跌额')),
            'change_pct': _to_float(row.get('涨跌幅')),
            'open': _to_float(row.get('今开')),
            'high': _to_float(row.get('最高')),
            'low': _to_float(row.get('最低')),
            'prev_close': _to_float(row.get('昨收')),
            'volume': _to_float(row.get('成交量')),
            'turnover': _to_float(row.get('成交额')),
        })
    _cache_set('indices', result)
    return result


def fetch_index_trend(days=120, ttl=300):
    """多指数收盘价序列 + 归一化涨跌幅（相对窗口首日）。"""
    cache_key = f'trend_{days}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    series = []
    for code, name in TREND_INDICES:
        df = _safe_df_call(
            ak.stock_zh_index_daily, symbol=code, source_name=f'sina_index_daily_{code}'
        )
        if df is None or df.empty:
            continue
        df = df.copy()
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df = df.sort_values('date').tail(days)
        closes = []
        for _, r in df.iterrows():
            closes.append({
                'date': str(r['date']),
                'close': _to_float(r.get('close')),
                'volume': _to_float(r.get('volume')),
            })
        if not closes:
            continue
        base = closes[0]['close']
        for item in closes:
            if base and item['close'] is not None:
                item['norm_pct'] = round((item['close'] / base - 1) * 100, 3)
            else:
                item['norm_pct'] = None
        series.append({
            'code': code,
            'name': name,
            'items': closes,
            'period_change_pct': closes[-1].get('norm_pct'),
        })

    data = {
        'available': bool(series),
        'days': days,
        'series': series,
        'message': '' if series else '指数日线暂不可用',
    }
    _cache_set(cache_key, data)
    return data
