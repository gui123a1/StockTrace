"""
手动触发股票数据拉取的管理命令

用法：
    python manage.py fetch_stock_data 000001     # 拉取单只股票
    python manage.py fetch_stock_data --all       # 拉取所有关注股票
    python manage.py fetch_stock_data 000001 --days 60  # 指定历史天数
"""

from django.core.management.base import BaseCommand
from stocks.models import Stock
from stocks.services import fetch_stock_all_data, fetch_all_active_stocks


class Command(BaseCommand):
    help = '拉取股票数据（日K线 + 分钟K线）'

    def add_arguments(self, parser):
        parser.add_argument(
            'code', type=str, nargs='?', help='股票代码（如 000001）'
        )
        parser.add_argument(
            '--all', action='store_true', help='拉取所有关注股票'
        )
        parser.add_argument(
            '--days', type=int, default=5, help='分钟数据回溯天数（默认5天）'
        )

    def handle(self, *args, **options):
        if options['all']:
            self.stdout.write('正在拉取所有关注股票数据...')
            results = fetch_all_active_stocks()
            for r in results:
                if r['status'] == 'success':
                    self.stdout.write(
                        self.style.SUCCESS(f"  {r['code']}: 成功，{r.get('count', 0)} 条日K线")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f"  {r['code']}: 失败 - {r.get('message', '')}")
                    )
        elif options['code']:
            code = options['code']
            try:
                stock = Stock.objects.get(code=code)
            except Stock.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"股票 {code} 不在关注列表中"))
                return

            self.stdout.write(f'正在拉取 {stock.code} {stock.name} 数据...')
            count = fetch_stock_all_data(stock, days_back=options['days'])
            self.stdout.write(
                self.style.SUCCESS(f"完成，{count} 条日K线数据")
            )
        else:
            self.stdout.write(self.style.ERROR('请指定股票代码或使用 --all'))
