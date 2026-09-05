"""条件选股引擎：结构化条件 DSL + 在最新日线数据上执行。

DSL 示例：
{
  "logic": "all",              # all=AND / any=OR
  "conditions": [
    {"field": "change_pct", "op": "gt", "value": 3},
    {"field": "turnover", "op": "between", "value": [50000000, 2000000000]},
    {"field": "above_ma20", "op": "eq", "value": 1}
  ],
  "order_by": "change_pct",    # 可选
  "order_dir": "desc",         # asc/desc，默认 desc
  "limit": 20                  # 可选
}

数据全部来自 DailyQuote 真实落库数据；多日字段（均线/区间涨跌/量比等）
由最近 ≤61 根日线现算。任何字段因历史不足或数据缺失取不到值时为 None，
该股此条件不命中（如实的「未知」，不当 0，遵守数据诚信红线）。
"""
from dataclasses import dataclass

from ..models import Stock

# 计算多日指标所需的最大回看根数（60日涨跌幅需要 61 根：基准+最新）
MAX_LOOKBACK = 61

# 布尔类字段（值 1=成立 / 0=不成立），前端渲染为「是/否」下拉
BOOL_FIELDS = {
    'above_ma5', 'above_ma10', 'above_ma20', 'above_ma60',
    'ma5_gt_ma10', 'ma5_gt_ma20',
    'new_high_20d', 'new_low_20d',
}

OPS = {'gt', 'gte', 'lt', 'lte', 'eq', 'between'}


@dataclass
class ConditionError(Exception):
    message: str

    def __str__(self):
        return self.message


def _f(dec):
    return float(dec) if dec is not None else None


def _closes(ctx, n):
    """最近 n 根收盘价（float 列表，升序，尾元素最新）；根数不足或含缺失返回 None。"""
    bars = ctx['bars'][-n:]
    if len(bars) < n:
        return None
    closes = [_f(b.close_price) for b in bars]
    if any(c is None for c in closes) or closes[-1] is None:
        return None
    return closes


def _pct_n(n):
    """区间涨跌幅：最新收盘 / n 根前收盘 - 1。"""
    def getter(ctx):
        closes = _closes(ctx, n + 1)
        if not closes or closes[0] == 0:
            return None
        return (closes[-1] / closes[0] - 1) * 100
    return getter


def _above_ma(n):
    """收盘价站上 n 日均线（>=）。"""
    def getter(ctx):
        closes = _closes(ctx, n)
        if not closes:
            return None
        ma = sum(closes) / n
        return 1 if closes[-1] >= ma else 0
    return getter


def _ma_gt(short, long):
    """短均线严格在长均线上方。"""
    def getter(ctx):
        closes = _closes(ctx, long)
        if not closes:
            return None
        ma_short = sum(closes[-short:]) / short
        ma_long = sum(closes) / long
        return 1 if ma_short > ma_long else 0
    return getter


def _new_extreme(n, high):
    """最新收盘创最近 n 根（含当日）收盘的新高/新低。"""
    def getter(ctx):
        closes = _closes(ctx, n)
        if not closes:
            return None
        last = closes[-1]
        rest = closes[:-1]
        if high:
            return 1 if last >= max(rest) else 0
        return 1 if last <= min(rest) else 0
    return getter


def _volume_ratio(ctx):
    """量比：今日成交量 / 前 5 根均量。"""
    bars = ctx['bars']
    if len(bars) < 6:
        return None
    today = _f(bars[-1].volume)
    base = [_f(b.volume) for b in bars[-6:-1]]
    if not today or any(v is None or v == 0 for v in base):
        return None
    return today / (sum(base) / 5)


def _turnover_5d_avg(ctx):
    """近 5 根（含最新）日均成交额（元）。"""
    bars = ctx['bars']
    if len(bars) < 5:
        return None
    vals = [_f(b.turnover) for b in bars[-5:]]
    if any(v is None for v in vals):
        return None
    return sum(vals) / 5


def _pct_from_high_20d(ctx):
    """距最近 20 根最高收盘的回撤（≤0，0 表示正在新高）。"""
    closes = _closes(ctx, 20)
    if not closes:
        return None
    peak = max(closes)
    if peak == 0:
        return None
    return (closes[-1] / peak - 1) * 100


def _up_days(ctx):
    """连续上涨天数：从最新一根往前数收盘连涨（相等即断）。"""
    bars = ctx['bars']
    if len(bars) < 2:
        return None
    closes = [_f(b.close_price) for b in bars]
    if closes[-1] is None or closes[-2] is None:
        return None
    days = 0
    i = len(closes) - 1
    while i >= 1 and closes[i] is not None and closes[i - 1] is not None:
        if closes[i] > closes[i - 1]:
            days += 1
            i -= 1
        else:
            break
    return days


# 可筛选字段：key -> (中文名, 取值函数, 说明)
# 取值函数输入 ctx（dict：quote=最新日线, bars=升序日线列表），返回 float/None
FIELDS = {
    # ---- 当日字段（来自最新一根日线） ----
    'close_price': ('收盘价', lambda ctx: _f(ctx['quote'].close_price), '元'),
    'open_price': ('开盘价', lambda ctx: _f(ctx['quote'].open_price), '元'),
    'high_price': ('最高价', lambda ctx: _f(ctx['quote'].high_price), '元'),
    'low_price': ('最低价', lambda ctx: _f(ctx['quote'].low_price), '元'),
    'change_pct': ('涨跌幅', lambda ctx: _f(ctx['quote'].change_pct), '%，相对昨收'),
    'open_close_pct': ('日内涨幅', lambda ctx: _f(ctx['quote'].open_close_pct), '%，(收盘-开盘)/开盘'),
    'high_low_pct': ('日内振幅', lambda ctx: _f(ctx['quote'].high_low_pct), '%，(最高-最低)/最低'),
    'volume': ('成交量', lambda ctx: _f(ctx['quote'].volume), '手'),
    'turnover': ('成交额', lambda ctx: _f(ctx['quote'].turnover), '元'),
    # ---- 多日衍生字段（由最近 ≤61 根日线现算） ----
    'pct_5d': ('5日涨跌幅', _pct_n(5), '%'),
    'pct_10d': ('10日涨跌幅', _pct_n(10), '%'),
    'pct_20d': ('20日涨跌幅', _pct_n(20), '%'),
    'pct_60d': ('60日涨跌幅', _pct_n(60), '%'),
    'volume_ratio': ('量比(今量/5日均量)', _volume_ratio, '倍'),
    'turnover_5d_avg': ('5日日均成交额', _turnover_5d_avg, '元'),
    'pct_from_high_20d': ('距20日最高收盘回撤', _pct_from_high_20d, '%，≤0'),
    'up_days': ('连续上涨天数', _up_days, '天'),
    'above_ma5': ('收盘站上5日线', _above_ma(5), '1是/0否'),
    'above_ma10': ('收盘站上10日线', _above_ma(10), '1是/0否'),
    'above_ma20': ('收盘站上20日线', _above_ma(20), '1是/0否'),
    'above_ma60': ('收盘站上60日线', _above_ma(60), '1是/0否'),
    'ma5_gt_ma10': ('5日线在10日线上方', _ma_gt(5, 10), '1是/0否'),
    'ma5_gt_ma20': ('5日线在20日线上方', _ma_gt(5, 20), '1是/0否'),
    'new_high_20d': ('创20日新高', _new_extreme(20, high=True), '1是/0否'),
    'new_low_20d': ('创20日新低', _new_extreme(20, high=False), '1是/0否'),
}


def _history_ctx(stock, quote):
    """组装字段计算上下文：最新日线 + 最近 ≤61 根（升序，尾元素最新）。"""
    bars = list(stock.daily_quotes.order_by('-trade_date')[:MAX_LOOKBACK])
    bars.reverse()
    return {'stock': stock, 'quote': quote, 'bars': bars}


def _latest_contexts():
    """每只活跃股票的 (stock, 最新日线 ctx)；当日无行情的股票不参与。"""
    result = []
    for stock in Stock.objects.filter(is_active=True):
        quote = stock.daily_quotes.order_by('-trade_date').first()
        if quote is not None:
            result.append((stock, _history_ctx(stock, quote)))
    return result


def _match(op, value, target):
    if op == 'between':
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ConditionError('between 操作符的 value 必须是 [下限, 上限]')
        lo, hi = float(value[0]), float(value[1])
        return lo <= target <= hi
    if op == 'gt':
        return target > value
    if op == 'gte':
        return target >= value
    if op == 'lt':
        return target < value
    if op == 'lte':
        return target <= value
    if op == 'eq':
        return target == value
    raise ConditionError(f'不支持的操作符：{op}')


def _validate(spec):
    if not isinstance(spec, dict):
        raise ConditionError('筛选条件必须是 JSON 对象')
    logic = spec.get('logic', 'all')
    if logic not in ('all', 'any'):
        raise ConditionError('logic 只能是 all（且）或 any（或）')
    conditions = spec.get('conditions')
    if not isinstance(conditions, list) or not conditions:
        raise ConditionError('conditions 必须是非空数组')
    for cond in conditions:
        if not isinstance(cond, dict):
            raise ConditionError('每个条件必须是对象')
        field = cond.get('field')
        op = cond.get('op')
        if field not in FIELDS:
            raise ConditionError(
                f'不支持的字段：{field}，可选：{", ".join(FIELDS)}'
            )
        if op not in OPS:
            raise ConditionError(f'不支持的操作符：{op}，可选：{", ".join(sorted(OPS))}')
        if 'value' not in cond:
            raise ConditionError('条件缺少 value')
        if op != 'between' and not isinstance(cond['value'], (int, float)):
            raise ConditionError(f'{field} {op} 的 value 必须是数字')
        if field in BOOL_FIELDS and op != 'between' \
                and cond['value'] not in (0, 1):
            raise ConditionError(f'{field} 是布尔字段，value 只能是 0 或 1')
    order_by = spec.get('order_by')
    if order_by is not None and order_by not in FIELDS:
        raise ConditionError(f'排序字段不支持：{order_by}')


def run_screener(spec):
    """执行筛选，返回结果列表（含股票信息与命中的字段值）"""
    _validate(spec)
    logic = spec.get('logic', 'all')
    conditions = spec['conditions']

    rows = []
    for stock, ctx in _latest_contexts():
        values = {key: fn(ctx) for key, (_, fn, _) in FIELDS.items()}

        results = []
        for cond in conditions:
            target = values[cond['field']]
            # 该股此项无数据 → 该条件不命中（如实的"未知"，不当作 0）
            if target is None:
                results.append(False)
                continue
            try:
                results.append(_match(cond['op'], cond['value'], target))
            except (TypeError, ValueError):
                raise ConditionError(f"条件 {cond['field']} {cond['op']} 的 value 类型不合法")
        matched = all(results) if logic == 'all' else any(results)
        if not matched:
            continue

        row = {
            'stock_id': stock.id,
            'code': stock.code,
            'name': stock.name,
            'trade_date': ctx['quote'].trade_date.isoformat(),
        }
        row.update({k: values[k] for k in values if values[k] is not None})
        rows.append(row)

    order_by = spec.get('order_by')
    if order_by:
        desc = spec.get('order_dir', 'desc') != 'asc'
        rows.sort(
            key=lambda r: r.get(order_by) if r.get(order_by) is not None else float('-inf'),
            reverse=desc,
        )
    limit = spec.get('limit')
    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]
    return rows
