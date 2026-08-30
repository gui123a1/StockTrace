from collections import Counter

import akshare as ak
import pandas as pd
from django.core.management.base import BaseCommand

from stocks.market import _etf_row_to_item, _parse_fund_flow_table


ETF_FIELDS = (
    '最新份额', '成交额', '总市值', '流通市值', '主力净流入-净额',
    '基金折价率', 'IOPV实时估值', '数据日期', '更新时间',
)
REPRESENTATIVE_ETFS = (
    ('510300', '沪市宽基'),
    ('159915', '深市宽基'),
    ('512480', '行业主题'),
    ('511010', '债券'),
    ('518880', '商品'),
    ('513100', '跨境'),
)


class Command(BaseCommand):
    help = '人工校验 ETF/板块上游字段、覆盖率与研究用 ETF 范围规则（只读）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--history-code',
            action='append',
            dest='history_codes',
            help='仅校验指定 ETF 日线；可重复传入。默认校验代表性样本',
        )

    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(f'== {title} =='))

    def _report_frame_error(self, label, exc):
        self.stdout.write(self.style.ERROR(f'{label}失败（已跳过，不中止其他校验）: {exc}'))

    def _validate_etf_spot(self):
        self._section('ETF 全市场快照')
        try:
            frame = ak.fund_etf_spot_em()
        except Exception as exc:
            self._report_frame_error('ETF 全表', exc)
            return None, []

        self.stdout.write(self.style.SUCCESS(f'返回 {len(frame)} 行，{len(frame.columns)} 列'))
        self.stdout.write(f'字段：{list(frame.columns)}')

        code_series = frame['代码'].astype(str).str.zfill(6) if '代码' in frame.columns else pd.Series(dtype=str)
        missing_codes = int(code_series.isna().sum() + (code_series == '').sum())
        duplicate_codes = int(code_series.duplicated(keep=False).sum())
        self.stdout.write(f'代码缺失：{missing_codes}；重复记录：{duplicate_codes}')

        for col in ETF_FIELDS:
            if col not in frame.columns:
                self.stdout.write(self.style.WARNING(f'{col}: 字段缺失'))
                continue
            series = frame[col]
            non_null = int(series.notna().sum())
            ratio = non_null / len(frame) if len(frame) else 0
            samples = [str(value) for value in series.dropna().head(3).tolist()]
            self.stdout.write(f'{col}: 非空 {non_null}/{len(frame)} ({ratio:.1%})；样本 {samples}')

        normalized = [_etf_row_to_item(row) for _, row in frame.iterrows()]
        reason_counts = Counter(item['scope_match_reason'] for item in normalized)
        matched = [item for item in normalized if item['scope_match']]
        unmatched = [item for item in normalized if not item['scope_match']]
        self.stdout.write(
            f'股票/宽基规则命中：{len(matched)}；排除/未判定：{len(unmatched)}；'
            f'覆盖率：{len(matched) / len(normalized):.1%}' if normalized else 'ETF 规范化结果为空'
        )
        self.stdout.write(f'规则原因统计：{dict(reason_counts)}')

        for title, items in (('命中样本', matched), ('排除/未判定样本', unmatched)):
            sample = [
                f"{item['code']} {item['name']} ({item['scope_match_reason']})"
                for item in items[:12]
            ]
            self.stdout.write(f'{title}：{sample}')

        self._section('代表性 ETF 分类检查')
        by_code = {item['code']: item for item in normalized}
        for code, category in REPRESENTATIVE_ETFS:
            item = by_code.get(code)
            if not item:
                self.stdout.write(self.style.WARNING(f'{category} {code}: 快照中不存在'))
                continue
            self.stdout.write(
                f"{category} {code} {item['name']}: scope_match={item['scope_match']}，"
                f"原因={item['scope_match_reason']}"
            )

        return frame, normalized

    def _validate_sectors(self):
        self._section('行业 / 概念资金流')
        for label, loader, candidates in (
            ('行业', ak.stock_fund_flow_industry, ['行业']),
            ('概念', ak.stock_fund_flow_concept, ['行业', '概念']),
        ):
            try:
                frame = loader()
                parsed = _parse_fund_flow_table(frame, candidates)
            except Exception as exc:
                self._report_frame_error(f'{label}资金', exc)
                continue

            name_col = next((col for col in candidates if col in frame.columns), None)
            duplicate_names = (
                int(frame[name_col].astype(str).duplicated(keep=False).sum())
                if name_col else None
            )
            positive = sum(1 for item in parsed if item['net'] > 0)
            negative = sum(1 for item in parsed if item['net'] < 0)
            self.stdout.write(self.style.SUCCESS(
                f'{label}: 上游 {len(frame)} 行，规范化 {len(parsed)} 行，'
                f'净流入 {positive}，净流出 {negative}，名称重复 {duplicate_names}'
            ))
            self.stdout.write(f'{label}字段：{list(frame.columns)}')
            self.stdout.write(f'{label}样本：{parsed[:3]}')

    def _validate_history(self, requested_codes):
        self._section('单 ETF 日线历史')
        if requested_codes:
            samples = [(str(code).zfill(6), '指定样本') for code in requested_codes]
        else:
            samples = REPRESENTATIVE_ETFS

        for code, category in samples:
            try:
                frame = ak.fund_etf_hist_em(
                    symbol=code,
                    period='daily',
                    start_date='20260101',
                    end_date='20991231',
                    adjust='',
                )
            except Exception as exc:
                self._report_frame_error(f'{category} ETF {code} 日线', exc)
                continue

            if frame is None or frame.empty:
                self.stdout.write(self.style.WARNING(f'{category} ETF {code}: 日线为空'))
                continue
            first_date = frame.iloc[0].get('日期')
            last_date = frame.iloc[-1].get('日期')
            self.stdout.write(self.style.SUCCESS(
                f'{category} ETF {code}: {len(frame)} 行，覆盖 {first_date} → {last_date}'
            ))
            self.stdout.write(f'字段：{list(frame.columns)}')

    def handle(self, *args, **options):
        self.stdout.write('本命令只读取上游数据：不写数据库、不修改市场缓存、不注册定时任务。')
        self._validate_etf_spot()
        self._validate_sectors()
        self._validate_history(options.get('history_codes'))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('校验流程结束；请同时检查上方的失败/缺失警告。'))
