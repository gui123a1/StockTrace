"""
大盘 / 市场数据服务（进程内缓存，适合 1H2G VPS）。

数据源策略：
- 与 stocks.services 类似：多源 failover，而不是死磕东财。
- 源池冷却（cooldown）：某源连续失败后暂时跳过，降低东财限流概率（简易「负载均衡」）。
- 指数优先新浪；北向历史可用；大盘主力东财失败则用北向净买额序列兜底。

说明：
- 「国家队 ETF」为市场常用宽基/政策相关 ETF 监控列表，非官方实时持仓披露。
- 「机构持仓」来自季报汇总 / 股东变动统计 / 北向资金，非实时成交持仓。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from decimal import InvalidOperation

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# 源失败冷却：秒（东财限流时拉长）
_SOURCE_COOLDOWN_SEC = 180
_SOURCE_FAIL_THRESHOLD = 2
_source_lock = threading.Lock()
# name -> {fails, cool_until, last_ok, last_err}
_source_state = {}

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

# 国家队 / 汇金 常相关的宽基与政策向 ETF（6 位代码）
NATIONAL_TEAM_ETFS = [
    ('510050', '上证50ETF'),
    ('510300', '沪深300ETF'),
    ('159919', '沪深300ETF嘉实'),
    ('510500', '中证500ETF'),
    ('159915', '创业板ETF'),
    ('512100', '中证1000ETF'),
    ('588000', '科创50ETF'),
    ('510180', '上证180ETF'),
    ('159901', '深证100ETF'),
    ('512000', '券商ETF'),
    ('512880', '证券ETF'),
    ('512010', '医药ETF'),
    ('159995', '芯片ETF'),
    ('515790', '光伏ETF'),
    ('512480', '半导体ETF'),
    ('512690', '酒ETF'),
    ('518880', '黄金ETF'),
    ('511010', '国债ETF'),
]

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


def _source_is_cool(name):
    st = _source_state.get(name) or {}
    until = st.get('cool_until') or 0
    return time.time() < until


def _source_mark_ok(name):
    with _source_lock:
        _source_state[name] = {
            'fails': 0,
            'cool_until': 0,
            'last_ok': time.time(),
            'last_err': '',
        }


def _source_mark_fail(name, err):
    with _source_lock:
        st = _source_state.get(name) or {'fails': 0, 'cool_until': 0}
        st['fails'] = int(st.get('fails') or 0) + 1
        st['last_err'] = str(err)[:200]
        if st['fails'] >= _SOURCE_FAIL_THRESHOLD:
            st['cool_until'] = time.time() + _SOURCE_COOLDOWN_SEC
            logger.warning(
                f"数据源 {name} 连续失败 {st['fails']} 次，冷却 {_SOURCE_COOLDOWN_SEC}s: {err}"
            )
        else:
            logger.warning(f"数据源 {name} 失败 ({st['fails']}): {err}")
        _source_state[name] = st


def _safe_df_call(fn, *args, source_name=None, **kwargs):
    """单次调用；可选 source_name 参与冷却统计。"""
    name = source_name or getattr(fn, '__name__', 'unknown')
    if _source_is_cool(name):
        logger.debug(f"跳过冷却中的数据源 {name}")
        return None
    try:
        result = fn(*args, **kwargs)
        if result is None or (isinstance(result, pd.DataFrame) and result.empty):
            _source_mark_fail(name, 'empty')
            return None
        _source_mark_ok(name)
        return result
    except Exception as e:
        _source_mark_fail(name, e)
        return None


def _try_source_fns(candidates):
    """
    按序尝试多个 (name, callable) 数据源。
    冷却中的源排后；成功返回 (name, df)。
    这是「轮询 + failover」，不是跨机负载均衡，但能分散对单一东财接口的压力。
    """
    if not candidates:
        return None, None

    def sort_key(item):
        name = item[0]
        cool = 1 if _source_is_cool(name) else 0
        fails = (_source_state.get(name) or {}).get('fails', 0)
        return (cool, fails)

    ordered = sorted(candidates, key=sort_key)
    # 仍保持相对优先级：先把未冷却的按原顺序，再冷却的
    cool = [c for c in candidates if _source_is_cool(c[0])]
    hot = [c for c in candidates if not _source_is_cool(c[0])]
    ordered = hot + cool

    last_err = None
    for name, fn in ordered:
        try:
            if _source_is_cool(name) and name != ordered[-1][0]:
                # 非最后手段时跳过冷却源
                continue
            result = fn()
            if result is None or (isinstance(result, pd.DataFrame) and result.empty):
                _source_mark_fail(name, 'empty')
                continue
            _source_mark_ok(name)
            logger.info(f"市场数据源 {name} 成功")
            return name, result
        except Exception as e:
            last_err = e
            _source_mark_fail(name, e)
    logger.error(f"市场数据源全部失败，最后错误: {last_err}")
    return None, None


def get_source_health():
    """调试用：各源冷却状态。"""
    now = time.time()
    out = {}
    with _source_lock:
        for name, st in _source_state.items():
            out[name] = {
                'fails': st.get('fails', 0),
                'cooling': bool(st.get('cool_until', 0) > now),
                'cool_remaining_sec': max(0, int((st.get('cool_until') or 0) - now)),
                'last_err': st.get('last_err', ''),
            }
    return out


# ── 指数 ──────────────────────────────────────────────

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


# ── 北向 / 情绪 / 主力 ────────────────────────────────

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


# ── 板块资金轮动 ──────────────────────────────────────

_SECTOR_SORT_FIELDS = {
    'net': 'net',
    'inflow': 'inflow',
    'outflow': 'outflow',
    'change_pct': 'change_pct',
    'leader_pct': 'leader_pct',
}


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


def fetch_concept_fund_flow(ttl=180):
    cache_key = 'concept_ff_all'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached
    df = _safe_df_call(ak.stock_fund_flow_concept, source_name='em_fund_flow_concept')
    data = _parse_fund_flow_table(df, ['行业', '概念'])
    _cache_set(cache_key, data)
    return data


def fetch_industry_fund_flow(ttl=180):
    cache_key = 'industry_ff_all'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached
    df = _safe_df_call(ak.stock_fund_flow_industry, source_name='em_fund_flow_industry')
    data = _parse_fund_flow_table(df, ['行业'])
    _cache_set(cache_key, data)
    return data


def _sort_items(items, field, order):
    """数值字段排序；同值使用代码/名称兜底，保证分页结果稳定。"""
    present = [item for item in items if item.get(field) is not None]
    missing = [item for item in items if item.get(field) is None]
    tie_key = lambda item: str(item.get('code') or item.get('name') or '')
    present.sort(key=tie_key)
    present.sort(key=lambda item: item[field], reverse=order == 'desc')
    missing.sort(key=tie_key)
    return present + missing


def _paginate(items, page, page_size):
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    return items[start:start + page_size], {
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_pages': total_pages,
    }


def _sector_payload(items, board, q='', sort='net', order='desc', page=1, page_size=50):
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
        'period': 'day',
        'supported_periods': ['day'],
        'unavailable_periods': ['5d', '10d', '20d'],
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


def get_sector_rotation(board='industry', q='', sort='net', order='desc', page=1, page_size=50):
    if board not in ('industry', 'concept'):
        raise ValueError('board 必须是 industry 或 concept')
    if sort not in _SECTOR_SORT_FIELDS:
        raise ValueError('不支持的板块排序字段')
    if order not in ('asc', 'desc'):
        raise ValueError('order 必须是 asc 或 desc')

    loader = fetch_industry_fund_flow if board == 'industry' else fetch_concept_fund_flow
    payload = _sector_payload(loader(), board, q=q, sort=sort, order=order, page=page, page_size=page_size)
    cache_key = 'industry_ff_all' if board == 'industry' else 'concept_ff_all'
    return {
        'updated_at': _now_str(),
        'meta': _cache_meta(
            cache_key,
            180,
            f'akshare.stock_fund_flow_{board}',
            payload['available'],
            disclaimer=payload['methodology'],
        ),
        **payload,
    }


# ── ETF 全表缓存 + 国家队 / 份额雷达 ───────────────────

def _fetch_etf_spot_df(ttl=180, force=False):
    """全市场 ETF 现货（较重，单独缓存）。"""
    if not force:
        cached = _cache_get('etf_spot_df', ttl)
        if cached is not None:
            return cached

    df = _safe_df_call(ak.fund_etf_spot_em, source_name='em_etf_spot')
    if df is None or df.empty:
        return _stale_or('etf_spot_df', None)

    _cache_set('etf_spot_df', df)
    return df


_ETF_SORT_FIELDS = {
    'share': 'share',
    'market_cap': 'market_cap',
    'turnover': 'turnover',
    'main_net': 'main_net',
    'change_pct': 'change_pct',
    'turnover_rate': 'turnover_rate',
    'discount_rate': 'discount_rate',
}
_ETF_RANK_SORT = {
    'share': ('share', 'desc'),
    'market_cap': ('market_cap', 'desc'),
    'turnover': ('turnover', 'desc'),
    'main_inflow': ('main_net', 'desc'),
    'main_outflow': ('main_net', 'asc'),
    'gainer': ('change_pct', 'desc'),
    'loser': ('change_pct', 'asc'),
}
_ETF_SCOPE_EXCLUDE_RULES = (
    ('货币/现金管理 ETF', ('货币ETF', '货币基金', '保证金', '场内货币', '理财金')),
    ('债券 ETF', ('国债ETF', '政金债', '信用债', '城投债', '可转债', '转债ETF', '债券ETF', '地方债', '公司债')),
    ('商品 ETF', ('黄金ETF', '黄金9999', '白银ETF', '原油ETF', '豆粕ETF', '商品ETF', '大宗商品ETF')),
    ('境外市场 ETF', ('纳指', '纳斯达克', '标普', '日经', '德国ETF', '法国ETF', '沙特ETF', '东南亚', '中概互联', '中概互联网')),
    ('香港市场 ETF', ('恒生', '港股', '港股通', '恒科', '香港证券')),
)
_ETF_SCOPE_RULE_VERSION = 'equity-broad-v2'


def _etf_scope(item):
    """
    研究用股票/宽基范围：上游暂无稳定基金类型字段，因此采用可审计名称规则。
    排除词要求足够具体，避免误伤自由现金流、黄金股、有色金属等股票 ETF。
    """
    name = item['name'].upper()
    for category, keywords in _ETF_SCOPE_EXCLUDE_RULES:
        matched = next((keyword for keyword in keywords if keyword.upper() in name), None)
        if matched:
            return False, f'{category}:{matched}'
    if 'ETF' in name or '交易型开放式指数' in name:
        return True, '股票/宽基候选:ETF名称规则'
    return False, '无法判定:未命中ETF名称规则'


def _etf_row_to_item(row):
    code = str(row.get('代码', '')).zfill(6)
    item = {
        'code': code,
        'name': str(row.get('名称', '')).strip(),
        'exchange': 'SH' if code.startswith('5') else ('SZ' if code.startswith('1') else None),
        'price': _to_float(row.get('最新价')),
        'iopv': _to_float(row.get('IOPV实时估值')),
        'discount_rate': _to_float(row.get('基金折价率')),
        'change': _to_float(row.get('涨跌额')),
        'change_pct': _to_float(row.get('涨跌幅')),
        'volume': _to_float(row.get('成交量')),
        'turnover': _to_float(row.get('成交额')),
        'prev_close': _to_float(row.get('昨收')),
        'open': _to_float(row.get('今开')),
        'high': _to_float(row.get('最高')),
        'low': _to_float(row.get('最低')),
        'amplitude': _to_float(row.get('振幅')),
        'volume_ratio': _to_float(row.get('量比')),
        'turnover_rate': _to_float(row.get('换手率')),
        'main_net': _to_float(row.get('主力净流入-净额')),
        'main_net_pct': _to_float(row.get('主力净流入-净占比')),
        'super_large_net': _to_float(row.get('超大单净流入-净额')),
        'large_net': _to_float(row.get('大单净流入-净额')),
        'medium_net': _to_float(row.get('中单净流入-净额')),
        'small_net': _to_float(row.get('小单净流入-净额')),
        'share': _to_float(row.get('最新份额')),
        'float_market_cap': _to_float(row.get('流通市值')),
        'market_cap': _to_float(row.get('总市值')),
        'data_date': str(row.get('数据日期', ''))[:10],
        'source_updated_at': str(row.get('更新时间', '')),
    }
    scope_match, reason = _etf_scope(item)
    item['scope_match'] = scope_match
    item['scope_match_reason'] = reason
    return item


def _normalized_etf_items(ttl=180):
    df = _fetch_etf_spot_df(ttl=ttl)
    if df is None or df.empty:
        return []
    items = []
    seen = set()
    for _, row in df.iterrows():
        item = _etf_row_to_item(row)
        if not item['code'] or item['code'] in seen:
            continue
        seen.add(item['code'])
        items.append(item)
    return items


def get_etf_share_radar(
    scope='equity_broad', rank='share', sort=None, order=None, q='',
    min_turnover=None, page=1, page_size=50, ttl=180, force=False,
):
    if scope not in ('equity_broad', 'all'):
        raise ValueError('scope 必须是 equity_broad 或 all')
    if rank not in _ETF_RANK_SORT:
        raise ValueError('不支持的 ETF 排行维度')
    if sort is not None and sort not in _ETF_SORT_FIELDS:
        raise ValueError('不支持的 ETF 排序字段')
    if order is not None and order not in ('asc', 'desc'):
        raise ValueError('order 必须是 asc 或 desc')

    if force:
        _fetch_etf_spot_df(ttl=ttl, force=True)
    all_items = _normalized_etf_items(ttl=ttl)
    scoped_items = [item for item in all_items if item['scope_match']] if scope == 'equity_broad' else list(all_items)
    if q:
        needle = q.lower()
        scoped_items = [item for item in scoped_items if needle in item['code'].lower() or needle in item['name'].lower()]
    if min_turnover is not None:
        scoped_items = [item for item in scoped_items if item.get('turnover') is not None and item['turnover'] >= min_turnover]

    default_sort, default_order = _ETF_RANK_SORT[rank]
    sort_field = sort or default_sort
    sort_order = order or default_order
    sorted_items = _sort_items(scoped_items, _ETF_SORT_FIELDS[sort_field], sort_order)
    page_items, pagination = _paginate(sorted_items, page, page_size)
    total_main = sum(item['main_net'] for item in scoped_items if item.get('main_net') is not None)
    total_turnover = sum(item['turnover'] for item in scoped_items if item.get('turnover') is not None)
    data_dates = [item['data_date'] for item in scoped_items if item.get('data_date')]

    return {
        'updated_at': _now_str(),
        'available': bool(all_items),
        'meta': _cache_meta(
            'etf_spot_df',
            ttl,
            'akshare.fund_etf_spot_em',
            bool(all_items),
            source_data_date=max(data_dates) if data_dates else None,
            disclaimer='最新份额与资金流为市场源当前快照；股票/宽基范围为研究用规则筛选，非基金官方分类。',
        ),
        'scope': {
            'active': scope,
            'rule_version': _ETF_SCOPE_RULE_VERSION,
            'all_count': len(all_items),
            'equity_broad_count': sum(1 for item in all_items if item['scope_match']),
        },
        'summary': {
            'count': len(scoped_items),
            'share_available_count': sum(1 for item in scoped_items if item.get('share') is not None),
            'positive_main_net_count': sum(1 for item in scoped_items if (item.get('main_net') or 0) > 0),
            'negative_main_net_count': sum(1 for item in scoped_items if (item.get('main_net') or 0) < 0),
            'total_main_net': total_main,
            'total_turnover': total_turnover,
        },
        'rank': rank,
        'sort': sort_field,
        'order': sort_order,
        'pagination': pagination,
        'items': page_items,
        'supported_metrics': {
            'share_change_1d': False,
            'share_change_5d': False,
            'share_change_20d': False,
            'reason': '一期未保存 ETF 日度份额快照',
        },
        'message': '' if all_items else 'ETF 行情暂不可用',
    }


def _etf_history(code, range_name='3m', ttl=1200):
    cache_key = f'etf_history_{code}_{range_name}'
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    days = {'1m': 45, '3m': 120, '6m': 240, '1y': 400}[range_name]
    end = datetime.now().date()
    start = end - timedelta(days=days)
    df = _safe_df_call(
        ak.fund_etf_hist_em,
        symbol=code,
        period='daily',
        start_date=start.strftime('%Y%m%d'),
        end_date=end.strftime('%Y%m%d'),
        adjust='',
        source_name=f'em_etf_history_{code}',
    )
    if df is None or df.empty:
        return _stale_or(cache_key, [])

    items = []
    for _, row in df.iterrows():
        items.append({
            'date': str(row.get('日期', ''))[:10],
            'open': _to_float(row.get('开盘')),
            'close': _to_float(row.get('收盘')),
            'high': _to_float(row.get('最高')),
            'low': _to_float(row.get('最低')),
            'volume': _to_float(row.get('成交量')),
            'turnover': _to_float(row.get('成交额')),
            'change_pct': _to_float(row.get('涨跌幅')),
            'turnover_rate': _to_float(row.get('换手率')),
        })
    _cache_set(cache_key, items)
    return items


def _period_return(history, bars):
    closes = [item['close'] for item in history if item.get('close') is not None]
    if len(closes) <= bars or not closes[-bars - 1]:
        return None
    return round((closes[-1] / closes[-bars - 1] - 1) * 100, 3)


def get_etf_detail(code, range_name='3m'):
    if not (str(code).isdigit() and len(str(code)) == 6):
        raise ValueError('ETF 代码必须是 6 位数字')
    if range_name not in ('1m', '3m', '6m', '1y'):
        raise ValueError('range 必须是 1m、3m、6m 或 1y')

    quote = next((item for item in _normalized_etf_items() if item['code'] == code), None)
    if quote is None:
        raise ValueError('未在 ETF 行情中找到该代码')
    history = _etf_history(code, range_name=range_name)
    history_key = f'etf_history_{code}_{range_name}'
    history_dates = [item['date'] for item in history if item.get('date')]
    return {
        'meta': _cache_meta(
            'etf_spot_df',
            180,
            'akshare.fund_etf_spot_em',
            bool(quote),
            source_data_date=quote.get('data_date'),
            disclaimer='当前行情为 ETF 市场快照；历史图为市场价格日线，不代表基金份额历史。',
        ),
        'instrument': {'code': quote['code'], 'name': quote['name'], 'exchange': quote['exchange']},
        'quote': quote,
        'price_performance': {
            'return_5d': _period_return(history, 5),
            'return_20d': _period_return(history, 20),
            'return_60d': _period_return(history, 60),
        },
        'share_metrics': {
            'latest_share': quote.get('share'),
            'availability': 'latest_only',
            'message': '一期未积累日度份额快照，暂不提供 1/5/20 日份额变化。',
        },
        'history': {
            'range': range_name,
            'interval': '1d',
            'available': bool(history),
            'count': len(history),
            'start_date': min(history_dates) if history_dates else None,
            'end_date': max(history_dates) if history_dates else None,
            'meta': _cache_meta(
                history_key,
                1200,
                'akshare.fund_etf_hist_em',
                bool(history),
                source_data_date=max(history_dates) if history_dates else None,
                disclaimer='仅为 ETF 市场价格日线；不包含历史份额。',
            ),
            'items': history,
        },
    }


def get_national_team_etfs(ttl=180, force=False):
    """国家队相关 ETF 观察名单，不代表官方持仓披露。"""
    cache_key = 'national_etf'
    if force:
        _fetch_etf_spot_df(ttl=ttl, force=True)
    elif (cached := _cache_get(cache_key, ttl)) is not None:
        return cached

    by_code = {item['code']: item for item in _normalized_etf_items(ttl=ttl)}
    items = []
    for code, fallback_name in NATIONAL_TEAM_ETFS:
        item = dict(by_code.get(code) or {
            'code': code,
            'name': fallback_name,
            'price': None,
            'change_pct': None,
            'share': None,
            'main_net': None,
        })
        item['listed'] = code in by_code
        if not item.get('name'):
            item['name'] = fallback_name
        items.append(item)

    listed = [item for item in items if item['listed']]
    total_main = sum(item['main_net'] for item in listed if item.get('main_net') is not None)
    total_share = sum(item['share'] for item in listed if item.get('share') is not None)
    total_market_cap = sum(item['market_cap'] for item in listed if item.get('market_cap') is not None)
    data_dates = [item['data_date'] for item in listed if item.get('data_date')]
    data = {
        'updated_at': _now_str(),
        'available': bool(listed),
        'mode': 'watchlist',
        'official_disclosure_available': False,
        'watchlist_definition': {
            'maintained_by': 'StockTrace curated list',
            'basis': '市场常用宽基与政策相关 ETF 的研究观察清单',
            'is_official_holding': False,
        },
        'meta': _cache_meta(
            'etf_spot_df',
            ttl,
            'akshare.fund_etf_spot_em + curated watchlist',
            bool(listed),
            source_data_date=max(data_dates) if data_dates else None,
            disclaimer='该页面是宽基/政策相关 ETF 观察名单，不是国家队官方持仓披露。',
        ),
        'disclaimer': '该页面是宽基/政策相关 ETF 观察名单，不是国家队官方持仓披露，不提供持仓主体、持仓比例或持仓成本。',
        'summary': {
            'count': len(listed),
            'total_main_net': total_main if listed else None,
            'total_share': total_share if listed else None,
            'total_market_cap': total_market_cap if listed else None,
        },
        'items': items,
        'message': '' if listed else 'ETF 行情暂不可用',
    }
    _cache_set(cache_key, data)
    return data


# ── 聚合 ──────────────────────────────────────────────

# ── 机构持仓 ──────────────────────────────────────────

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
    y, m = now.year, now.month
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


def get_market_overview():
    """数据首页：指数 + 资金情绪摘要（不拉重型 ETF 全表）。"""
    indices = fetch_major_indices()
    hsgt = fetch_hsgt_flow()
    activity = fetch_market_activity()
    fund_hist = fetch_market_fund_flow_hist(days=30)
    concept_items = fetch_concept_fund_flow()
    concept = _sector_payload(concept_items, 'concept', page=1, page_size=8)

    north_net = 0.0
    north_has = False
    for row in hsgt:
        if row.get('direction') == '北向' and row.get('net_buy') is not None:
            north_net += row['net_buy']
            north_has = True

    return {
        'updated_at': _now_str(),
        'indices': indices,
        'fund': {
            'hsgt': hsgt,
            'northbound_net_buy': north_net if north_has else None,
            'activity': activity,
            'main_hist': fund_hist,
            'concept': concept,
        },
        'modules': [
            {
                'key': 'trend',
                'title': '全市场走势',
                'desc': '上证/深成/创业板/沪深300/科创50 归一化对比',
                'path': '/market/trend',
            },
            {
                'key': 'sectors',
                'title': '板块资金轮动',
                'desc': '行业与概念资金净流入/流出排行',
                'path': '/market/sectors',
            },
            {
                'key': 'institutions',
                'title': '机构持仓',
                'desc': '国内外机构持股变化、北向资金与个股机构明细',
                'path': '/market/institutions',
            },
            {
                'key': 'national-etf',
                'title': '国家队相关 ETF 观察',
                'desc': '宽基与政策相关 ETF 观察名单（非官方持仓）',
                'path': '/market/national-etf',
            },
            {
                'key': 'etf-radar',
                'title': 'ETF 份额雷达',
                'desc': '份额规模、主力净流入/流出与涨跌榜',
                'path': '/market/etf-radar',
            },
        ],
        'sources_health': get_source_health(),
    }


def get_market_trend():
    return {
        'updated_at': _now_str(),
        **fetch_index_trend(days=120),
    }


def warm_post_close_lagging():
    """
    收盘后降频预热：只刷新可能晚到的行情缓存。
    不写自选 SQLite，不拉已冻结的指数现价/涨跌家数/板块当日排名/机构季报。
    """
    started = time.time()
    logger.info("收盘后晚到数据预热开始")

    try:
        fetch_hsgt_flow(force=True)
    except Exception as e:
        logger.error(f"预热北向资金失败: {e}")
    time.sleep(0.8)

    try:
        fetch_market_fund_flow_hist(days=30, force=True)
    except Exception as e:
        logger.error(f"预热大盘资金历史失败: {e}")
    time.sleep(0.8)

    try:
        # force 一次 ETF 现货表，再重建两个派生缓存
        _fetch_etf_spot_df(force=True)
        get_national_team_etfs(force=True)
        get_etf_share_radar(force=True)
    except Exception as e:
        logger.error(f"预热 ETF 份额/雷达失败: {e}")

    logger.info(f"收盘后晚到数据预热结束，耗时 {time.time() - started:.1f}s")
