"""条件选股引擎：结构化条件 DSL + 在最新日线数据上执行。

DSL 示例：
{
  "logic": "all",              # all=AND / any=OR
  "conditions": [
    {"field": "change_pct", "op": "gt", "value": 3},
    {"field": "turnover", "op": "between", "value": [50000000, 2000000000]}
  ],
  "order_by": "change_pct",    # 可选
  "order_dir": "desc",         # asc/desc，默认 desc
  "limit": 20                  # 可选
}

数据全部来自 DailyQuote 真实落库数据，取每只活跃股票最新一条日线；
当日没有行情的股票不参与筛选（不是补 0，遵守数据诚信红线）。
"""
from dataclasses import dataclass

from ..models import Stock

# 可筛选字段：key -> (中文名, 取值函数, 说明)
# 取值函数输入 DailyQuote，返回 float 或 None（None 表示该股此项无数据）
FIELDS = {
    'close_price': ('收盘价', lambda q: _f(q.close_price), '元'),
    'open_price': ('开盘价', lambda q: _f(q.open_price), '元'),
    'high_price': ('最高价', lambda q: _f(q.high_price), '元'),
    'low_price': ('最低价', lambda q: _f(q.low_price), '元'),
    'change_pct': ('涨跌幅', lambda q: _f(q.change_pct), '%，相对昨收'),
    'open_close_pct': ('日内涨幅', lambda q: _f(q.open_close_pct), '%，(收盘-开盘)/开盘'),
    'high_low_pct': ('日内振幅', lambda q: _f(q.high_low_pct), '%，(最高-最低)/最低'),
    'volume': ('成交量', lambda q: float(q.volume) if q.volume is not None else None, '手'),
    'turnover': ('成交额', lambda q: _f(q.turnover), '元'),
}

OPS = {'gt', 'gte', 'lt', 'lte', 'eq', 'between'}


@dataclass
class ConditionError(Exception):
    message: str

    def __str__(self):
        return self.message


def _f(dec):
    return float(dec) if dec is not None else None


def _latest_quotes():
    """每只活跃股票的最新一条日线"""
    stocks = Stock.objects.filter(is_active=True)
    result = []
    for stock in stocks:
        quote = stock.daily_quotes.order_by('-trade_date').first()
        if quote is not None:
            result.append((stock, quote))
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
    order_by = spec.get('order_by')
    if order_by is not None and order_by not in FIELDS:
        raise ConditionError(f'排序字段不支持：{order_by}')


def run_screener(spec):
    """执行筛选，返回结果列表（含股票信息与命中的字段值）"""
    _validate(spec)
    logic = spec.get('logic', 'all')
    conditions = spec['conditions']

    rows = []
    for stock, quote in _latest_quotes():
        values = {key: fn(quote) for key, (_, fn, _) in FIELDS.items()}

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
            'trade_date': quote.trade_date.isoformat(),
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
