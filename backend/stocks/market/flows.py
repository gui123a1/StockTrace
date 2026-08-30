"""北向资金 / 涨跌家数情绪 / 大盘主力资金历史。"""

from __future__ import annotations

import akshare as ak
import pandas as pd

from ._cache import _cache_get, _cache_set, _stale_or, _to_float
from ._sources import _safe_df_call, _source_is_cool, _source_mark_fail, _source_mark_ok


def fetch_hsgt_flow(ttl=120, force=False):
    if not force:
        cached = _cache_get('hsgt', ttl)
        if cached is not None:
            return cached

    df = _safe_df_call(ak.stock_hsgt_fund_flow_summary_em, source_name='em_hsgt_summary')
    if df is None or df.empty:
        return _stale_or('hsgt', [])

    rows = []
    for _, r in df.iterrows():
        rows.append({
            'trade_date': str(r.get('交易日', '')),
            'type': str(r.get('类型', '')),
            'board': str(r.get('板块', '')),
            'direction': str(r.get('资金方向', '')),
            'trade_status': r.get('交易状态'),
            'net_buy': _to_float(r.get('成交净买额')),
            'net_inflow': _to_float(r.get('资金净流入')),
            'balance': _to_float(r.get('当日资金余额')),
            'up_count': int(r['上涨数']) if pd.notna(r.get('上涨数')) else None,
            'flat_count': int(r['持平数']) if pd.notna(r.get('持平数')) else None,
            'down_count': int(r['下跌数']) if pd.notna(r.get('下跌数')) else None,
            'related_index': str(r.get('相关指数', '')),
            'index_change_pct': _to_float(r.get('指数涨跌幅')),
        })
    _cache_set('hsgt', rows)
    return rows


def fetch_market_activity(ttl=120):
    cached = _cache_get('activity', ttl)
    if cached is not None:
        return cached

    df = _safe_df_call(ak.stock_market_activity_legu, source_name='legu_activity')
    if df is None or df.empty:
        return _stale_or('activity', {})

    raw = {}
    for _, r in df.iterrows():
        raw[str(r.get('item', '')).strip()] = r.get('value')

    def pick(*keys):
        for k in keys:
            if k in raw:
                return raw[k]
        return None

    data = {
        'up': _to_float(pick('上涨')),
        'limit_up': _to_float(pick('涨停')),
        'real_limit_up': _to_float(pick('真实涨停')),
        'st_limit_up': _to_float(pick('st st*涨停')),
        'down': _to_float(pick('下跌')),
        'limit_down': _to_float(pick('跌停')),
        'real_limit_down': _to_float(pick('真实跌停')),
        'st_limit_down': _to_float(pick('st st*跌停')),
        'flat': _to_float(pick('平盘')),
        'suspended': _to_float(pick('停牌')),
        'activity': str(pick('活跃度') or ''),
        'stat_time': str(pick('统计日期') or ''),
    }
    _cache_set('activity', data)
    return data


def _normalize_market_fund_hist(df, days, source_name):
    """把不同源的资金历史表统一成 items 列表。"""
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return None

    work = df.copy()
    colmap = {}
    for c in work.columns:
        s = str(c)
        if '日期' in s or s.lower() == 'date':
            colmap[c] = 'date'
        elif '主力净流入' in s or s in ('当日成交净买额', '当日资金流入', 'main_net'):
            # 北向 hist 用净买额/资金流入近似「大盘外资流入」
            if 'main_net' not in colmap.values():
                colmap[c] = 'main_net'
        elif '小单净流入' in s:
            colmap[c] = 'small_net'
        elif '中单净流入' in s:
            colmap[c] = 'mid_net'
        elif '大单净流入' in s and '超大' not in s:
            colmap[c] = 'large_net'
        elif '超大单净流入' in s:
            colmap[c] = 'super_net'
    if colmap:
        work = work.rename(columns=colmap)

    if 'date' not in work.columns:
        return None

    work['date'] = work['date'].astype(str)
    work = work.sort_values('date').tail(days)

    items = []
    for _, r in work.iterrows():
        items.append({
            'date': str(r.get('date', ''))[:10],
            'main_net': _to_float(r.get('main_net')),
            'small_net': _to_float(r.get('small_net')),
            'mid_net': _to_float(r.get('mid_net')),
            'large_net': _to_float(r.get('large_net')),
            'super_net': _to_float(r.get('super_net')),
        })
    if not items:
        return None
    return {
        'available': True,
        'items': items,
        'message': '',
        'source': source_name,
    }


def fetch_market_fund_flow_hist(days=30, ttl=300, force=False):
    """
    大盘资金历史：
    1) 东财 stock_market_fund_flow（主力净流入，最完整）
    2) 东财北向历史 stock_hsgt_hist_em（净买额兜底，口径不同但可看趋势）
    带源冷却，避免东财挂了还反复打。
    """
    cache_key = f'market_ff_{days}'
    if not force:
        cached = _cache_get(cache_key, ttl)
        if cached is not None:
            return cached

    def load_em_main():
        return ak.stock_market_fund_flow()

    def load_north_hist():
        return ak.stock_hsgt_hist_em(symbol='北向资金')

    # 手工轮询以便 normalize
    candidates = [
        ('eastmoney_market_fund_flow', load_em_main),
        ('eastmoney_hsgt_hist_north', load_north_hist),
    ]
    cool = [c for c in candidates if _source_is_cool(c[0])]
    hot = [c for c in candidates if not _source_is_cool(c[0])]
    ordered = hot + cool

    data = None
    for name, fn in ordered:
        if _source_is_cool(name) and name != ordered[-1][0]:
            continue
        try:
            raw = fn()
            if raw is None or (isinstance(raw, pd.DataFrame) and raw.empty):
                _source_mark_fail(name, 'empty')
                continue
            parsed = _normalize_market_fund_hist(raw, days, name)
            if not parsed:
                _source_mark_fail(name, 'normalize_empty')
                continue
            _source_mark_ok(name)
            # 北向兜底时提示口径
            if name == 'eastmoney_hsgt_hist_north':
                parsed['message'] = '东财大盘主力暂不可用，已用北向资金净买额序列兜底（口径不同）'
            data = parsed
            break
        except Exception as e:
            _source_mark_fail(name, e)

    if data is None:
        data = _stale_or(
            cache_key,
            {
                'available': False,
                'items': [],
                'message': '大盘资金历史暂不可用（多源均失败）',
                'source': None,
            },
        )
    else:
        _cache_set(cache_key, data)
    return data
