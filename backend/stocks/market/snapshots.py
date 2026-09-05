"""市场日度快照：收盘后落库 + 多日趋势指标计算。

设计要点：
- 快照由收盘后预热任务（warm_post_close_lagging）末尾写入，幂等（同日重跑覆盖）；
- 多日指标按「窗口内快照齐全才算数」：缺任何一天就如实不可用，不拿 0/旧值补天；
- 板块 20 日轮动、ETF 份额 1/5/20 日变化由本模块供数（上游只给当日/原生 5d/10d）。
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from ..models import MarketDailySnapshot

logger = logging.getLogger(__name__)

# 快照落库失败重试无意义（预热任务每 30 分钟自然重试），单次失败只记日志
_SECTOR_SNAPSHOT_KINDS = {
    MarketDailySnapshot.KIND_INDUSTRY_FF: 'fetch_industry_fund_flow',
    MarketDailySnapshot.KIND_CONCEPT_FF: 'fetch_concept_fund_flow',
}
_ETF_SNAPSHOT_FIELDS = ('code', 'name', 'share', 'market_cap')
_MAX_CALENDAR_LOOKBACK_DAYS = 120


def save_daily_snapshots(trade_date=None):
    """把当日板块资金流与 ETF 份额写入快照表；返回 {'kind': 条数} 与失败项。

    幂等：同一 (kind, trade_date) 重跑覆盖。数据不可用时该 kind 当天没有行，
    不写空快照（保证多日指标的「齐全才算数」不被空行污染）。
    """
    from . import etf  # 延迟导入避免与 etf.py 的快照读路径成环

    trade_date = trade_date or timezone.localdate()
    saved = {}

    for kind, func_name in _SECTOR_SNAPSHOT_KINDS.items():
        try:
            from . import sectors
            items = getattr(sectors, func_name)(period='day')
            payload = [
                {'name': item['name'], 'net': item['net'], 'change_pct': item.get('change_pct')}
                for item in items if item.get('name')
            ]
            if payload:
                MarketDailySnapshot.objects.update_or_create(
                    kind=kind, trade_date=trade_date, defaults={'payload': payload},
                )
                saved[kind] = len(payload)
            else:
                logger.warning(f"{kind} 快照当日无数据，不写行（{trade_date}）")
        except Exception as e:
            logger.error(f"{kind} 快照落库失败: {e}")

    try:
        rows = [
            {field: item.get(field) for field in _ETF_SNAPSHOT_FIELDS}
            for item in etf._normalized_etf_items()
            if item.get('code') and item.get('share') is not None
        ]
        if rows:
            MarketDailySnapshot.objects.update_or_create(
                kind=MarketDailySnapshot.KIND_ETF_SHARE,
                trade_date=trade_date,
                defaults={'payload': rows},
            )
            saved[MarketDailySnapshot.KIND_ETF_SHARE] = len(rows)
        else:
            logger.warning(f"etf_share 快照当日无数据，不写行（{trade_date}）")
    except Exception as e:
        logger.error(f"etf_share 快照落库失败: {e}")

    return saved


def _recent_trading_days(n, end_date=None):
    """截止 end_date（含）往前数 n 个已完成交易日；不足时返回 None（含日历不可用）。"""
    from ..services import is_trading_day

    end_date = end_date or timezone.localdate()
    days = []
    day = end_date
    for _ in range(_MAX_CALENDAR_LOOKBACK_DAYS):
        if is_trading_day(day):
            days.append(day)
            if len(days) == n:
                days.reverse()
                return days
        day -= timedelta(days=1)
    return None


def _latest_snapshot(kind):
    return MarketDailySnapshot.objects.filter(kind=kind).order_by('-trade_date').first()


def _expected_latest_date():
    """最近一个已完成交易日的日期（15:30 后才算当天，覆盖快照写入时点）。

    日历不可用时返回 None（调用方按「无法校验时效」处理）。
    """
    from datetime import time as dt_time, timedelta

    from ..services import is_trading_day

    now = timezone.localtime()
    day = now.date()
    for _ in range(_MAX_CALENDAR_LOOKBACK_DAYS):
        if day < now.date() or now.time() >= dt_time(15, 30):
            try:
                if is_trading_day(day):
                    return day
            except Exception:
                return None
        day -= timedelta(days=1)
    return None


def _window_payloads(kind, n):
    """最近 n 个交易日的快照（以最新快照日为窗口末日）。

    返回 (payloads 按日期升序, latest)；窗口不齐、最新快照不是最近已完成
    交易日（即已过期）或日历不可用时返回 (None, latest)。
    """
    latest = _latest_snapshot(kind)
    if latest is None:
        return None, None
    expected = _recent_trading_days(n, end_date=latest.trade_date)
    if expected is None:
        return None, latest
    expected_today = _expected_latest_date()
    if expected_today is not None and latest.trade_date != expected_today:
        return None, latest
    rows = MarketDailySnapshot.objects.filter(
        kind=kind, trade_date__gte=expected[0], trade_date__lte=expected[-1],
    )
    by_date = {row.trade_date: row.payload for row in rows}
    if any(day not in by_date for day in expected):
        return None, latest
    return [by_date[day] for day in expected], latest


def sector_multiday_nets(kind, n):
    """板块 n 日净额合计：{name: net_sum}；窗口快照不齐返回 (None, covered_days)。

    按名字级别要求完整：某行业在窗口内缺任一天的行就不计入（回填可能只补到
    部分行业，不能让缺数据的行业被静默算少）。查库异常按「无快照」降级。
    """
    try:
        payloads, _latest = _window_payloads(kind, n)
        if payloads is None:
            covered = MarketDailySnapshot.objects.filter(kind=kind).count()
            return None, min(covered, n)
    except Exception:
        return None, 0
    totals = {}
    seen_days = {}
    for payload in payloads:
        names_in_day = set()
        for row in payload:
            name = row.get('name')
            net = row.get('net')
            if not name or net is None:
                continue
            totals[name] = totals.get(name, 0.0) + net
            names_in_day.add(name)
        for name in names_in_day:
            seen_days[name] = seen_days.get(name, 0) + 1
    complete = {name: total for name, total in totals.items() if seen_days[name] == n}
    if not complete:
        return None, n
    return complete, n


def share_change_map(n):
    """ETF 份额 n 日变化：{code: latest_share - n个交易日前_share}；窗口不齐返回 (None, covered)。

    「对比 n 个交易日前」需要 n+1 个快照点（首尾各一）；按代码级别要求首点有值。
    查库异常一律按「无快照」降级（雷达/详情主流程不因快照问题失败）。
    """
    try:
        payloads, latest = _window_payloads(MarketDailySnapshot.KIND_ETF_SHARE, n + 1)
        covered = MarketDailySnapshot.objects.filter(
            kind=MarketDailySnapshot.KIND_ETF_SHARE,
        ).count()
    except Exception:
        return None, 0
    if payloads is None:
        return None, min(covered, n)
    base = {row.get('code'): row.get('share') for row in payloads[0] if row.get('code')}
    changes = {}
    for row in payloads[-1]:
        code, share = row.get('code'), row.get('share')
        if not code or share is None or base.get(code) is None:
            continue
        changes[code] = share - base[code]
    return changes, n


def snapshot_meta(source, available, latest=None, message=''):
    """快照供数端点用的 meta（不走进程内缓存，状态只有 fresh/unavailable）。"""
    return {
        'available': bool(available),
        'source': source,
        'source_data_date': latest.trade_date.isoformat() if latest else None,
        'data_as_of': latest.trade_date.isoformat() if latest else None,
        'fetched_at': latest.created_at.isoformat(timespec='seconds') if latest else None,
        'cache_status': 'fresh' if available else 'unavailable',
        'disclaimer': '由本站收盘后日度快照计算；窗口内缺任一交易日即如实不可用。',
        **({'message': message} if message else {}),
    }
