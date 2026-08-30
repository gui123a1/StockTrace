"""板块资金轮动（行业 / 概念，当日横截面）。"""

from __future__ import annotations

import logging

import akshare as ak
import pandas as pd

from ._cache import _cache_get, _cache_meta, _cache_set, _now_str, _to_float
from ._query import _paginate, _sort_items
from ._sources import _safe_df_call

logger = logging.getLogger(__name__)

_SECTOR_SORT_FIELDS = {
    'net': 'net',
    'inflow': 'inflow',
    'outflow': 'outflow',
    'change_pct': 'change_pct',
    'leader_pct': 'leader_pct',
}

# 上游原生多日排行（东财 clist 接口，净额单位为元）；更长区间需日度快照积累
_SECTOR_RANK_INDICATORS = {'5d': '5日', '10d': '10日'}
_SECTOR_PERIODS = ('day', '5d', '10d')


def _parse_sector_rank_table(df):
    """解析 stock_sector_fund_flow_rank 的 clist 形状（列带指标前缀，单位为元）。"""
    if df is None or df.empty:
        return []
    name_col = next((c for c in ('行业', '板块名', '名称') if c in df.columns), None)
    net_col = next((c for c in df.columns if str(c).endswith('主力净流入-净额')), None)
    if name_col is None or net_col is None:
        return []
    pct_col = next((c for c in df.columns if str(c).endswith('涨跌幅')), None)

    items = []
    for _, row in df.iterrows():
        net = _to_float(row.get(net_col))
        if net is None:
            continue
        items.append({
            'name': str(row.get(name_col, '')).strip(),
            'net': net,
            'inflow': None,
            'outflow': None,
            'change_pct': _to_float(row.get(pct_col)) if pct_col else None,
            'index_value': None,
            'company_count': None,
            'leader': None,
            'leader_pct': None,
        })

    by_name = {}
    for item in items:
        if not item['name']:
            continue
        previous = by_name.get(item['name'])
        if previous is None or abs(item['net']) > abs(previous['net']):
            by_name[item['name']] = item
    return list(by_name.values())


def _parse_fund_flow_table(df, name_col_candidates):
    if df is None or df.empty:
        return []

    name_col = next((c for c in name_col_candidates if c in df.columns), None)
    if name_col is None:
        name_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    net_col = '净额' if '净额' in df.columns else None
    if net_col is None:
        return []

    in_col = '流入资金' if '流入资金' in df.columns else None
    out_col = '流出资金' if '流出资金' in df.columns else None
    pct_col = next((c for c in ('行业-涨跌幅', '涨跌幅') if c in df.columns), None)
    index_col = '行业指数' if '行业指数' in df.columns else None
    count_col = '公司家数' if '公司家数' in df.columns else None
    leader_col = '领涨股' if '领涨股' in df.columns else None
    leader_pct_col = '领涨股-涨跌幅' if '领涨股-涨跌幅' in df.columns else None

    items = []
    for _, row in df.iterrows():
        net = _to_float(row.get(net_col))
        if net is None:
            continue
        # AkShare 板块资金接口的金额单位为亿元，API 对外统一为元。
        items.append({
            'name': str(row.get(name_col, '')).strip(),
            'net': net * 1e8,
            'inflow': (_to_float(row.get(in_col)) * 1e8) if in_col and _to_float(row.get(in_col)) is not None else None,
            'outflow': (_to_float(row.get(out_col)) * 1e8) if out_col and _to_float(row.get(out_col)) is not None else None,
            'change_pct': _to_float(row.get(pct_col)) if pct_col else None,
            'index_value': _to_float(row.get(index_col)) if index_col else None,
            'company_count': int(row[count_col]) if count_col and pd.notna(row.get(count_col)) else None,
            'leader': str(row.get(leader_col, '')).strip() if leader_col else None,
            'leader_pct': _to_float(row.get(leader_pct_col)) if leader_pct_col else None,
        })

    # 上游横截面偶发同名记录；保留绝对净额较大的项，避免重复计入汇总和前端 key 冲突。
    by_name = {}
    for item in items:
        if not item['name']:
            continue
        previous = by_name.get(item['name'])
        if previous is None or abs(item['net']) > abs(previous['net']):
            by_name[item['name']] = item
    if len(by_name) != len(items):
        logger.warning(f"板块资金上游存在 {len(items) - len(by_name)} 条同名/空名记录，已规范化去重")
    return list(by_name.values())


def fetch_concept_fund_flow(period='day', ttl=180):
    cache_key = f'concept_ff_{period}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached
    if period == 'day':
        df = _safe_df_call(ak.stock_fund_flow_concept, source_name='em_fund_flow_concept')
        data = _parse_fund_flow_table(df, ['行业', '概念'])
    else:
        indicator = _SECTOR_RANK_INDICATORS[period]
        df = _safe_df_call(
            ak.stock_sector_fund_flow_rank, indicator=indicator,
            sector_type='概念资金流', source_name=f'em_sector_rank_concept_{period}',
        )
        data = _parse_sector_rank_table(df)
    _cache_set(cache_key, data)
    return data


def fetch_industry_fund_flow(period='day', ttl=180):
    cache_key = f'industry_ff_{period}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached
    if period == 'day':
        df = _safe_df_call(ak.stock_fund_flow_industry, source_name='em_fund_flow_industry')
        data = _parse_fund_flow_table(df, ['行业'])
    else:
        indicator = _SECTOR_RANK_INDICATORS[period]
        df = _safe_df_call(
            ak.stock_sector_fund_flow_rank, indicator=indicator,
            sector_type='行业资金流', source_name=f'em_sector_rank_industry_{period}',
        )
        data = _parse_sector_rank_table(df)
    _cache_set(cache_key, data)
    return data


def _sector_payload(items, board, period='day', q='', sort='net', order='desc', page=1, page_size=50):
    if q:
        needle = q.lower()
        items = [item for item in items if needle in item['name'].lower() or needle in (item.get('leader') or '').lower()]

    sorted_items = _sort_items(items, _SECTOR_SORT_FIELDS[sort], order)
    page_items, pagination = _paginate(sorted_items, page, page_size)
    inflow = sorted((item for item in items if item['net'] > 0), key=lambda item: item['net'], reverse=True)
    outflow = sorted((item for item in items if item['net'] < 0), key=lambda item: item['net'])
    neutral = [item for item in items if item['net'] == 0]
    positive_total = sum(item['net'] for item in inflow)
    top_three = sum(item['net'] for item in inflow[:3])
    total_net = sum(item['net'] for item in items)
    breadth = len(inflow) / len(items) * 100 if items else None
    divergences = [
        item for item in items
        if item.get('change_pct') is not None
        and ((item['net'] > 0 and item['change_pct'] < 0) or (item['net'] < 0 and item['change_pct'] > 0))
    ]
    divergences.sort(key=lambda item: abs(item['net']), reverse=True)

    return {
        'available': bool(items),
        'board': board,
        'period': period,
        'supported_periods': list(_SECTOR_PERIODS),
        'unavailable_periods': ['1m', '3m', '6m', '1y'],
        'unavailable_reason': '更长区间需要日度快照积累后开放',
        'summary': {
            'sample_count': len(items),
            'net_total': total_net if items else None,
            'inflow_count': len(inflow),
            'outflow_count': len(outflow),
            'neutral_count': len(neutral),
            'breadth_pct': breadth,
            'top_three_inflow_concentration_pct': (top_three / positive_total * 100) if positive_total else None,
            'strongest_inflow': inflow[0] if inflow else None,
            'strongest_outflow': outflow[0] if outflow else None,
        },
        'inflow_top': inflow[:8],
        'outflow_top': outflow[:8],
        'divergences': divergences[:6],
        'items': page_items,
        'pagination': pagination,
        'methodology': '板块资金为上游当日聚合强弱指标，不代表资金在板块之间的真实转移路径。',
    }


def get_sector_rotation(board='industry', period='day', q='', sort='net', order='desc', page=1, page_size=50):
    if board not in ('industry', 'concept'):
        raise ValueError('board 必须是 industry 或 concept')
    if period not in _SECTOR_PERIODS:
        raise ValueError('period 必须是 day、5d 或 10d')
    if sort not in _SECTOR_SORT_FIELDS:
        raise ValueError('不支持的板块排序字段')
    if order not in ('asc', 'desc'):
        raise ValueError('order 必须是 asc 或 desc')

    if board == 'industry':
        loader = fetch_industry_fund_flow
        cache_key = f'industry_ff_{period}'
    else:
        loader = fetch_concept_fund_flow
        cache_key = f'concept_ff_{period}'
    payload = _sector_payload(
        loader(period=period), board, period=period,
        q=q, sort=sort, order=order, page=page, page_size=page_size,
    )
    return {
        'updated_at': _now_str(),
        'meta': _cache_meta(
            cache_key,
            180,
            f'akshare.stock_fund_flow_{board}' if period == 'day'
            else f'akshare.stock_sector_fund_flow_rank({period})',
            payload['available'],
            disclaimer=payload['methodology'],
        ),
        **payload,
    }
