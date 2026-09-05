"""回填行业资金流日度快照（多日轮动指标的前置数据）。

用法（建议在 VPS 上跑，本地代理对 push2his.eastmoney.com 干扰严重）：
    python manage.py backfill_market_snapshots --days 60

说明：
- 上游历史接口 ak.stock_sector_fund_flow_hist 只有行业口径，单位为元
  （push2his fflow daykline，与当日排行一致），且不含涨跌幅列；
- 概念与 ETF 份额无上游历史，只能从今天起每日收盘后自动积累；
- 每个行业一次请求，间隔默认 0.5s；同 (行业, 日期) 重跑覆盖（幂等）。
"""

import time
from datetime import date as date_cls

import akshare as ak
from django.core.management.base import BaseCommand

from stocks.market import snapshots
from stocks.models import MarketDailySnapshot


class Command(BaseCommand):
    help = '回填行业资金流日度快照（仅行业口径；概念/ETF 份额只能向前积累）'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=60, help='回填最近 N 个交易日（默认 60）')
        parser.add_argument('--sleep', type=float, default=0.5, help='板块间间隔秒数（默认 0.5）')

    def handle(self, *args, **options):
        n_days = options['days']
        sleep_s = options['sleep']
        window = snapshots._recent_trading_days(n_days)
        if window is None:
            self.stderr.write('交易日历不可用或天数超出回看上限，中止')
            return
        start_date = window[0]
        self.stdout.write(f'回填 {start_date} 之后的行业资金流快照（约 {n_days} 个交易日）')

        # 行业名单与当日截面同源（stock_fund_flow_industry），保证口径一致
        try:
            from stocks.market.sectors import fetch_industry_fund_flow
            names = [item['name'] for item in fetch_industry_fund_flow(period='day')]
        except Exception as e:
            self.stderr.write(f'获取行业名单失败（{e}）；本地网络对 push2his 不稳定时请在 VPS 上执行')
            return
        if not names:
            self.stderr.write('行业名单为空，中止')
            return

        written_days = skipped = failed = 0
        for i, name in enumerate(names, 1):
            try:
                df = ak.stock_sector_fund_flow_hist(symbol=name)
            except Exception as e:
                failed += 1
                self.stderr.write(f'[{i}/{len(names)}] {name} 上游失败: {e}')
                time.sleep(sleep_s)
                continue
            if df is None or df.empty:
                skipped += 1
                continue

            days_here = 0
            for _, row in df.iterrows():
                day, net = row.get('日期'), row.get('主力净流入-净额')
                if not isinstance(day, date_cls) or day < start_date or net is None:
                    continue
                # 合并写入：该日快照可能已有完整截面（收盘任务写的），只替换本行业行
                snap, _ = MarketDailySnapshot.objects.get_or_create(
                    kind=MarketDailySnapshot.KIND_INDUSTRY_FF,
                    trade_date=day,
                    defaults={'payload': []},
                )
                payload = [r for r in (snap.payload or []) if r.get('name') != name]
                payload.append({'name': name, 'net': float(net), 'change_pct': None})
                snap.payload = payload
                snap.save(update_fields=['payload'])
                days_here += 1
            written_days += days_here
            self.stdout.write(f'[{i}/{len(names)}] {name}: {days_here} 天')
            time.sleep(sleep_s)

        self.stdout.write(self.style.SUCCESS(
            f'回填完成：累计写入 {written_days} 个 (行业, 日期) 快照；'
            f'空数据跳过 {skipped} 个行业；上游失败 {failed} 个行业'
        ))

        # 大盘主力资金流历史回补（东财恢复后可用；此后每日由收盘任务自动积累）
        try:
            from stocks.market import flows
            hist = flows.fetch_market_fund_flow_hist(days=130, force=True)
            items = (hist or {}).get('items', [])
            ff_written = 0
            for item in items:
                if not item.get('date'):
                    continue
                MarketDailySnapshot.objects.update_or_create(
                    kind=MarketDailySnapshot.KIND_MARKET_FF,
                    trade_date=date_cls.fromisoformat(item['date']),
                    defaults={'payload': [item]},
                )
                ff_written += 1
            self.stdout.write(self.style.SUCCESS(f'大盘资金流历史回补: {ff_written} 天'))
        except Exception as e:
            self.stderr.write(f'大盘资金流历史回补失败（上游恢复后重跑即可）: {e}')
