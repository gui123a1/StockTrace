"""机构持仓：季报机构持股、股东变动、北向序列与个股明细。"""

from __future__ import annotations

from datetime import datetime

import akshare as ak
import pandas as pd

from ._cache import _cache_get, _cache_set, _now_str, _stale_or, _to_float
from ._sources import _safe_df_call, get_source_health


def _recent_report_quarters(n=8):
    """生成候选季报代码：YYYY + 季度(1-4)，从当前往前推。"""
    now = datetime.now()
    y, m = now.year, now.month
    q = (m - 1) // 3 + 1
    # 季报披露滞后，先从上一完整季开始
    q -= 1
    if q <= 0:
        q = 4
        y -= 1
    out = []
    for _ in range(n):
        out.append(f'{y}{q}')
        q -= 1
        if q <= 0:
            q = 4
            y -= 1
    return out


def _quarter_label(code):
    """20243 -> 2024Q3"""
    s = str(code)
    if len(s) >= 5:
        return f'{s[:4]}Q{s[4]}'
    return s


def fetch_institute_hold_stocks(limit=40, ttl=600):
    """
    机构持股汇总（按股票）：机构数、持股比例及变化。
    数据源 stock_institute_hold(symbol=季度码)，自动找最近有数据的季度。
    """
    cache_key = f'inst_hold_stocks_{limit}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    quarter_used = None
    df = None
    for q in _recent_report_quarters(10):
        raw = _safe_df_call(
            ak.stock_institute_hold,
            symbol=q,
            source_name=f'em_institute_hold_{q}',
        )
        if raw is not None and not raw.empty and len(raw) > 0:
            df = raw
            quarter_used = q
            break

    if df is None or df.empty:
        data = {
            'available': False,
            'quarter': None,
            'quarter_label': None,
            'items': [],
            'message': '机构持股季报暂不可用',
        }
        return _stale_or(cache_key, data)

    work = df.copy()
    for col in ('机构数', '机构数变化', '持股比例', '持股比例增幅', '占流通股比例', '占流通股比例增幅'):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors='coerce')

    # 优先按机构数变化绝对值 / 持股比例增幅排序，突出「变化」
    if '机构数变化' in work.columns:
        work['_chg_abs'] = work['机构数变化'].abs()
        work = work.sort_values(['_chg_abs', '机构数'], ascending=[False, False])
    elif '持股比例增幅' in work.columns:
        work['_chg_abs'] = work['持股比例增幅'].abs()
        work = work.sort_values(['_chg_abs', '持股比例'], ascending=[False, False])
    else:
        work = work.sort_values('机构数', ascending=False) if '机构数' in work.columns else work

    items = []
    for _, r in work.head(limit).iterrows():
        items.append({
            'code': str(r.get('证券代码', '')).zfill(6),
            'name': str(r.get('证券简称', '')),
            'inst_count': int(r['机构数']) if pd.notna(r.get('机构数')) else None,
            'inst_count_chg': int(r['机构数变化']) if pd.notna(r.get('机构数变化')) else None,
            'hold_ratio': _to_float(r.get('持股比例')),
            'hold_ratio_chg': _to_float(r.get('持股比例增幅')),
            'float_ratio': _to_float(r.get('占流通股比例')),
            'float_ratio_chg': _to_float(r.get('占流通股比例增幅')),
        })

    data = {
        'available': True,
        'quarter': quarter_used,
        'quarter_label': _quarter_label(quarter_used) if quarter_used else None,
        'items': items,
        'message': '',
        'source': 'stock_institute_hold',
    }
    _cache_set(cache_key, data)
    return data


def fetch_institution_shareholder_changes(limit=40, ttl=900):
    """
    机构股东持仓变动统计（按机构）：总持有/新进/增加/减少只数、流通市值。
    数据较重，TTL 拉长；失败则降级。
    过滤掉纯「个人」股东，保留基金/保险/社保/QFII/券商/信托/国家队/其他机构等。
    """
    cache_key = f'inst_shareholder_chg_{limit}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    # 用最近季报日
    now = datetime.now()
    y = now.year
    # 候选报告期
    candidates = []
    for yy in (y, y - 1):
        for md in ('0930', '0630', '0331', '1231'):
            if yy == y and md == '1231':
                continue
            candidates.append(f'{yy}{md}')
    # 按时间近→远
    candidates = sorted(set(candidates), reverse=True)[:6]

    df = None
    date_used = None
    for d in candidates:
        raw = _safe_df_call(
            ak.stock_gdfx_free_holding_change_em,
            date=d,
            source_name=f'em_gdfx_free_chg_{d}',
        )
        if raw is not None and not raw.empty:
            df = raw
            date_used = d
            break

    if df is None or df.empty:
        data = {
            'available': False,
            'report_date': None,
            'items': [],
            'message': '机构股东变动统计暂不可用（接口重或限流）',
        }
        return _stale_or(cache_key, data)

    work = df.copy()
    if '股东类型' in work.columns:
        # 排除个人；保留机构类（含「其他」如香港中央结算）
        work = work[work['股东类型'].astype(str) != '个人']

    num_cols = [
        '期末持股只数统计-总持有', '期末持股只数统计-新进',
        '期末持股只数统计-增加', '期末持股只数统计-不变',
        '期末持股只数统计-减少', '流通市值统计',
    ]
    for col in num_cols:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors='coerce')

    if '流通市值统计' in work.columns:
        work = work.sort_values('流通市值统计', ascending=False)
    elif '期末持股只数统计-总持有' in work.columns:
        work = work.sort_values('期末持股只数统计-总持有', ascending=False)

    items = []
    for _, r in work.head(limit).iterrows():
        hold_str = str(r.get('持有个股', '') or '')
        # 持有个股字段很长，只取前几个展示
        samples = []
        for part in hold_str.split(',')[:5]:
            part = part.strip()
            if not part:
                continue
            if '|' in part:
                code, name = part.split('|', 1)
                samples.append({'code': code, 'name': name})
            else:
                samples.append({'code': '', 'name': part})
        items.append({
            'name': str(r.get('股东名称', '')),
            'type': str(r.get('股东类型', '')),
            'hold_count': int(r['期末持股只数统计-总持有']) if pd.notna(r.get('期末持股只数统计-总持有')) else None,
            'new_count': int(r['期末持股只数统计-新进']) if pd.notna(r.get('期末持股只数统计-新进')) else None,
            'increase_count': int(r['期末持股只数统计-增加']) if pd.notna(r.get('期末持股只数统计-增加')) else None,
            'flat_count': int(r['期末持股只数统计-不变']) if pd.notna(r.get('期末持股只数统计-不变')) else None,
            'decrease_count': int(r['期末持股只数统计-减少']) if pd.notna(r.get('期末持股只数统计-减少')) else None,
            'market_value': _to_float(r.get('流通市值统计')),
            'sample_stocks': samples,
        })

    data = {
        'available': True,
        'report_date': date_used,
        'items': items,
        'message': '',
        'source': 'stock_gdfx_free_holding_change_em',
        'disclaimer': '来自股东户数/流通股东统计，披露滞后；「其他」含香港中央结算等通道型股东。',
    }
    _cache_set(cache_key, data)
    return data


def fetch_northbound_flow_series(days=60, ttl=300):
    """北向资金历史序列（机构外资维度）。"""
    cache_key = f'north_series_{days}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    df = _safe_df_call(
        ak.stock_hsgt_hist_em,
        symbol='北向资金',
        source_name='em_hsgt_hist_north',
    )
    if df is None or df.empty:
        data = {'available': False, 'items': [], 'message': '北向资金历史暂不可用'}
        return _stale_or(cache_key, data)

    work = df.copy()
    # 列名已在探测中确认
    date_col = '日期' if '日期' in work.columns else work.columns[0]
    work[date_col] = work[date_col].astype(str)
    work = work.sort_values(date_col).tail(days)

    items = []
    for _, r in work.iterrows():
        items.append({
            'date': str(r.get(date_col, ''))[:10],
            'net_buy': _to_float(r.get('当日成交净买额')),
            'inflow': _to_float(r.get('当日资金流入')),
            'hold_mv': _to_float(r.get('持股市值')),
            'hs300_pct': _to_float(r.get('沪深300-涨跌幅')),
        })

    data = {
        'available': True,
        'items': items,
        'message': '',
        'source': 'stock_hsgt_hist_em',
    }
    _cache_set(cache_key, data)
    return data


def fetch_stock_institution_detail(code, ttl=600):
    """单只股票机构持仓明细 + 十大股东（可选查询）。"""
    code = str(code).zfill(6)
    cache_key = f'inst_detail_{code}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    # 机构明细：找最近有数据的季度
    inst_items = []
    quarter_used = None
    for q in _recent_report_quarters(8):
        raw = _safe_df_call(
            ak.stock_institute_hold_detail,
            stock=code,
            quarter=q,
            source_name=f'em_inst_detail_{code}_{q}',
        )
        if raw is not None and not raw.empty:
            quarter_used = q
            for _, r in raw.iterrows():
                inst_items.append({
                    'type': str(r.get('持股机构类型', '')),
                    'inst_code': str(r.get('持股机构代码', '')),
                    'inst_name': str(r.get('持股机构简称') or r.get('持股机构全称') or ''),
                    'shares': _to_float(r.get('最新持股数') if pd.notna(r.get('最新持股数')) else r.get('持股数')),
                    'ratio': _to_float(r.get('最新持股比例') if pd.notna(r.get('最新持股比例')) else r.get('持股比例')),
                    'float_ratio': _to_float(
                        r.get('最新占流通股比例') if pd.notna(r.get('最新占流通股比例')) else r.get('占流通股比例')
                    ),
                    'ratio_chg': _to_float(r.get('持股比例增幅')),
                })
            break

    # 十大流通股东
    holders = []
    raw_h = _safe_df_call(
        ak.stock_main_stock_holder,
        stock=code,
        source_name=f'em_main_holder_{code}',
    )
    if raw_h is not None and not raw_h.empty:
        # 取最近一个报告期
        date_col = '截至日期' if '截至日期' in raw_h.columns else None
        work = raw_h.copy()
        if date_col:
            latest = str(work[date_col].iloc[0])
            work = work[work[date_col].astype(str) == latest]
        for _, r in work.head(15).iterrows():
            holders.append({
                'rank': r.get('编号'),
                'name': str(r.get('股东名称', '')),
                'shares': _to_float(r.get('持股数量')),
                'ratio': _to_float(r.get('持股比例')),
                'nature': str(r.get('股本性质', '')),
                'as_of': str(r.get('截至日期', '')),
            })

    data = {
        'code': code,
        'available': bool(inst_items or holders),
        'quarter': quarter_used,
        'quarter_label': _quarter_label(quarter_used) if quarter_used else None,
        'institutions': inst_items,
        'top_holders': holders,
        'message': '' if (inst_items or holders) else '未查到该股机构/股东数据',
    }
    _cache_set(cache_key, data)
    return data


def get_institution_holdings(stock_code=None):
    """机构持仓专题页聚合。stock_code 可选，提供则附带个股明细。"""
    stocks = fetch_institute_hold_stocks(limit=40)
    orgs = fetch_institution_shareholder_changes(limit=30)
    north = fetch_northbound_flow_series(days=60)

    detail = None
    if stock_code:
        detail = fetch_stock_institution_detail(stock_code)

    return {
        'updated_at': _now_str(),
        'disclaimer': (
            '机构持仓来自公开季报/股东披露与北向统计，存在滞后；'
            '海外机构多通过 QFII、陆股通（香港中央结算）等通道体现，非实时成交持仓。'
        ),
        'by_stock': stocks,
        'by_institution': orgs,
        'northbound': north,
        'stock_detail': detail,
        'sources_health': get_source_health(),
    }
