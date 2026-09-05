"""新增功能测试：日度快照（板块 20 日轮动 / ETF 份额变化）、价格提醒、持仓成本、选股预设。

交易日历统一 patch 为「每天都交易日」，使窗口= 自然日窗口，保持确定性。
"""

import json

import pandas as pd
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from . import alerts, market
from .market import snapshots
from .models import (
    AlertEvent,
    DailyQuote,
    MarketDailySnapshot,
    MinuteBar,
    PriceAlert,
    Stock,
)
from .views import _quote_row

_BASE = date(2026, 9, 4)


def _trading_true(day=None):
    return True


def _make_sector_snapshots(kind, days, names_by_day):
    """days: 相对 _BASE 往前的天数列表；names_by_day: offset -> {name: net}"""
    for offset, nets in names_by_day.items():
        MarketDailySnapshot.objects.create(
            kind=kind,
            trade_date=_BASE - timedelta(days=offset),
            payload=[{'name': k, 'net': v, 'change_pct': None} for k, v in nets.items()],
        )


class SnapshotSaveTests(TestCase):
    def test_save_writes_industry_and_etf_but_skips_empty_concept(self):
        with patch(
            'stocks.market.sectors.fetch_industry_fund_flow',
            return_value=[{'name': '半导体', 'net': 1e8, 'change_pct': 1.5}],
        ), patch(
            'stocks.market.sectors.fetch_concept_fund_flow',
            return_value=[],
        ), patch(
            'stocks.market.etf._normalized_etf_items',
            return_value=[{'code': '510300', 'name': '300ETF', 'share': 100.0, 'market_cap': 400.0}],
        ):
            saved = snapshots.save_daily_snapshots(trade_date=_BASE)

        self.assertEqual(saved[MarketDailySnapshot.KIND_INDUSTRY_FF], 1)
        self.assertEqual(saved[MarketDailySnapshot.KIND_ETF_SHARE], 1)
        # 无数据不写行，不产生空快照
        self.assertNotIn(MarketDailySnapshot.KIND_CONCEPT_FF, saved)
        self.assertFalse(
            MarketDailySnapshot.objects.filter(kind=MarketDailySnapshot.KIND_CONCEPT_FF).exists()
        )

    def test_save_is_idempotent_same_day(self):
        items = [{'name': '半导体', 'net': 1e8, 'change_pct': 1.5}]
        with patch(
            'stocks.market.sectors.fetch_industry_fund_flow', return_value=items,
        ), patch(
            'stocks.market.sectors.fetch_concept_fund_flow', return_value=[],
        ), patch(
            'stocks.market.etf._normalized_etf_items', return_value=[],
        ):
            snapshots.save_daily_snapshots(trade_date=_BASE)
            items[0]['net'] = 2e8
            snapshots.save_daily_snapshots(trade_date=_BASE)

        row = MarketDailySnapshot.objects.get(
            kind=MarketDailySnapshot.KIND_INDUSTRY_FF, trade_date=_BASE,
        )
        self.assertEqual(row.payload[0]['net'], 2e8)  # 重跑覆盖而非新增


class SectorMultidayTests(TestCase):
    def _with_window(self):
        with patch('stocks.services.is_trading_day', _trading_true), patch(
            'stocks.market.snapshots._expected_latest_date', return_value=_BASE,
        ):
            return snapshots.sector_multiday_nets(
                MarketDailySnapshot.KIND_INDUSTRY_FF, 3,
            )

    def test_incomplete_window_is_unavailable(self):
        _make_sector_snapshots(MarketDailySnapshot.KIND_INDUSTRY_FF, 3, {
            0: {'A': 100.0},
            1: {'A': 50.0},
            # 缺 offset=2 的那天
        })
        nets, covered = self._with_window()
        self.assertIsNone(nets)
        self.assertEqual(covered, 2)

    def test_sums_and_excludes_names_with_missing_days(self):
        _make_sector_snapshots(MarketDailySnapshot.KIND_INDUSTRY_FF, 3, {
            0: {'A': 25.0},
            1: {'A': 50.0, 'B': 10.0},
            2: {'A': 100.0, 'B': 20.0},
        })
        nets, covered = self._with_window()
        self.assertEqual(nets, {'A': 175.0})  # B 只有一天，窗口不完整被剔除
        self.assertEqual(covered, 3)


class SectorRotation20dTests(TestCase):
    def test_20d_without_snapshots_honestly_reports_accumulation(self):
        result = market.get_sector_rotation(board='industry', period='20d')
        self.assertFalse(result['available'])
        self.assertIn('快照', result['message'])
        self.assertEqual(result['supported_periods'], ['day', '5d', '10d', '20d'])

    def test_20d_with_full_window_sums_daily_nets(self):
        _make_sector_snapshots(MarketDailySnapshot.KIND_INDUSTRY_FF, 20, {
            offset: {'半导体': 10.0} for offset in range(20)
        })
        with patch('stocks.services.is_trading_day', _trading_true), patch(
            'stocks.market.snapshots._expected_latest_date', return_value=_BASE,
        ):
            result = market.get_sector_rotation(
                board='industry', period='20d', sort='net', order='desc',
            )
        self.assertTrue(result['available'])
        self.assertEqual(result['items'][0]['net'], 200.0)
        self.assertTrue(result['meta']['available'])

    def test_20d_rejects_non_net_sort(self):
        with self.assertRaises(ValueError):
            market.get_sector_rotation(board='industry', period='20d', sort='change_pct')


class EtfShareChangeTests(TestCase):
    def _map(self, n):
        with patch('stocks.services.is_trading_day', _trading_true), patch(
            'stocks.market.snapshots._expected_latest_date', return_value=_BASE,
        ):
            return snapshots.share_change_map(n)

    def test_share_change_vs_n_trading_days_ago(self):
        shares = {0: 110.0, 1: 105.0, 2: 103.0, 3: 102.0, 4: 101.0, 5: 100.0}
        for offset, share in shares.items():
            MarketDailySnapshot.objects.create(
                kind=MarketDailySnapshot.KIND_ETF_SHARE,
                trade_date=_BASE - timedelta(days=offset),
                payload=[{'code': '510300', 'name': '300ETF', 'share': share, 'market_cap': None}],
            )
        chg, _covered = self._map(1)
        self.assertEqual(chg['510300'], 5.0)  # vs 1 个交易日前
        chg5, _ = self._map(5)
        self.assertEqual(chg5, {'510300': 10.0})  # vs 5 个交易日前（最早一天）

    def test_insufficient_window_returns_none(self):
        MarketDailySnapshot.objects.create(
            kind=MarketDailySnapshot.KIND_ETF_SHARE,
            trade_date=_BASE,
            payload=[{'code': '510300', 'name': '300ETF', 'share': 100.0, 'market_cap': None}],
        )
        chg, covered = self._map(5)
        self.assertIsNone(chg)
        self.assertEqual(covered, 1)

    def test_radar_attaches_changes_when_window_complete(self):
        for offset, share in ((0, 110.0), (1, 100.0)):
            MarketDailySnapshot.objects.create(
                kind=MarketDailySnapshot.KIND_ETF_SHARE,
                trade_date=_BASE - timedelta(days=offset),
                payload=[{'code': '510300', 'name': '300ETF', 'share': share, 'market_cap': None}],
            )
        with patch(
            'stocks.market.etf._fetch_etf_spot_df',
            return_value=pd.DataFrame([
                {'代码': '510300', '名称': '300ETF', '最新份额': 110, '成交额': 1000},
            ]),
        ), patch('stocks.services.is_trading_day', _trading_true), patch(
            'stocks.market.snapshots._expected_latest_date', return_value=_BASE,
        ):
            result = market.get_etf_share_radar()
        self.assertTrue(result['supported_metrics']['share_change_1d'])
        item = next(i for i in result['items'] if i['code'] == '510300')
        self.assertEqual(item['share_chg_1d'], 10.0)
        self.assertIsNone(item['share_chg_5d'])  # 窗口未凑齐如实为 null


def _make_quote(stock, close, change_pct, day=_BASE):
    return DailyQuote.objects.create(
        stock=stock, trade_date=day,
        open_price=close, close_price=close, high_price=close, low_price=close,
        open_close_diff=Decimal('0'), open_close_pct=Decimal('0'),
        high_low_diff=Decimal('0'), high_low_pct=Decimal('0'),
        change_pct=Decimal(str(change_pct)),
    )


class AlertEvaluationTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code='600000', name='浦发银行')

    def test_price_above_triggers_once_per_day(self):
        MinuteBar.objects.create(
            stock=self.stock, datetime=timezone.make_aware(datetime(2026, 9, 4, 10, 30)),
            open=Decimal('10'), close=Decimal('10.50'), high=Decimal('10.6'),
            low=Decimal('9.9'), volume=100,
        )
        PriceAlert.objects.create(
            stock=self.stock, rule_type=PriceAlert.PRICE_ABOVE, threshold=Decimal('9.5'),
        )
        with patch('stocks.services.is_trading_day', _trading_true):
            events = alerts.evaluate_alerts()
            self.assertEqual(len(events), 1)
            self.assertIn('上穿', events[0].message)
            # 同日不重复触发
            self.assertEqual(len(alerts.evaluate_alerts()), 0)

    def test_daily_pct_below_uses_positive_threshold(self):
        _make_quote(self.stock, Decimal('9.0'), -10.0)
        PriceAlert.objects.create(
            stock=self.stock, rule_type=PriceAlert.DAILY_PCT_BELOW, threshold=Decimal('5'),
        )
        with patch('stocks.services.is_trading_day', _trading_true):
            events = alerts.evaluate_alerts()
        self.assertEqual(len(events), 1)
        self.assertIn('跌幅', events[0].message)

    def test_missing_data_skips_without_fabrication(self):
        PriceAlert.objects.create(
            stock=self.stock, rule_type=PriceAlert.PRICE_ABOVE, threshold=Decimal('9.5'),
        )
        PriceAlert.objects.create(
            stock=self.stock, rule_type=PriceAlert.DAILY_PCT_ABOVE, threshold=Decimal('3'),
        )
        with patch('stocks.services.is_trading_day', _trading_true):
            events = alerts.evaluate_alerts()
        self.assertEqual(events, [])  # 无行情就不触发，绝不拿 0 凑数


class AlertApiTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code='600000', name='浦发银行')

    def test_create_list_mark_read_and_delete(self):
        response = self.client.post(
            '/api/alerts/',
            json.dumps({
                'stock_id': self.stock.id,
                'rule_type': PriceAlert.PRICE_ABOVE,
                'threshold': '10.5',
                'note': '突破提醒',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.get('/api/alerts/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['items']), 1)
        self.assertEqual(response.data['unread_count'], 0)

        AlertEvent.objects.create(
            alert_id=response.data['items'][0]['id'], stock=self.stock,
            message='测试触发', trade_date=_BASE,
        )
        response = self.client.get('/api/alerts/events/?unread=1')
        self.assertEqual(len(response.data), 1)
        response = self.client.post('/api/alerts/events/read/', {})
        self.assertEqual(response.data['marked'], 1)
        self.assertEqual(self.client.get('/api/alerts/events/?unread=1').data, [])

        response = self.client.delete('/api/alerts/1/')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get('/api/alerts/').data['items'], [])

    def test_invalid_rule_type_returns_400(self):
        response = self.client.post(
            '/api/alerts/',
            json.dumps({'stock_id': self.stock.id, 'rule_type': 'bad', 'threshold': '1'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_negative_price_threshold_returns_400(self):
        response = self.client.post(
            '/api/alerts/',
            json.dumps({'stock_id': self.stock.id, 'rule_type': PriceAlert.PRICE_ABOVE, 'threshold': '-1'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)


class ScreenerPresetApiTests(TestCase):
    SPEC = {'logic': 'all', 'conditions': [{'field': 'change_pct', 'op': 'gt', 'value': 3}]}

    def test_create_list_duplicate_and_delete(self):
        response = self.client.post(
            '/api/screener/presets/',
            json.dumps({'name': '强势股', 'spec': self.SPEC}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.get('/api/screener/presets/')
        user_presets = [p for p in response.data if not p['builtin']]
        self.assertEqual(len(user_presets), 1)
        self.assertEqual(user_presets[0]['spec'], self.SPEC)

        # 同名 409
        response = self.client.post('/api/screener/presets/', json.dumps({'name': '强势股', 'spec': self.SPEC}), content_type='application/json')
        self.assertEqual(response.status_code, 409)

        response = self.client.delete('/api/screener/presets/1/')
        self.assertEqual(response.status_code, 204)

    def test_invalid_spec_rejected_with_same_rules_as_execution(self):
        for bad in (
            {'conditions': []},
            {'logic': 'all', 'conditions': [{'field': 'nope', 'op': 'gt', 'value': 1}]},
            {'logic': 'all', 'conditions': [{'field': 'change_pct', 'op': 'nope', 'value': 1}]},
        ):
            with self.subTest(spec=bad):
                response = self.client.post('/api/screener/presets/', json.dumps({'name': 'x', 'spec': bad}), content_type='application/json')
                self.assertEqual(response.status_code, 400)


class DashboardCostTests(TestCase):
    def test_quote_row_carries_cost_fields(self):
        stock = Stock.objects.create(
            code='600000', name='浦发银行', cost_price=Decimal('10.000'), quantity=1000,
        )
        quote = _make_quote(stock, Decimal('11.0'), 10.0)
        row = _quote_row(stock, quote)
        self.assertEqual(row['cost_price'], Decimal('10.000'))
        self.assertEqual(row['quantity'], 1000)
        # 盈亏由前端按 (close - cost) * quantity 计算，后端不重复出口径

    def test_quote_row_without_cost_is_null(self):
        stock = Stock.objects.create(code='600000', name='浦发银行')
        row = _quote_row(stock, None)
        self.assertIsNone(row['cost_price'])
        self.assertIsNone(row['quantity'])


class MultiSourceRouterTests(SimpleTestCase):
    """_first_ok 多源路由：按优先级尝试、冷却跳过、全败返回 (None, None)。"""

    def setUp(self):
        from .market import _sources
        _sources._source_state.clear()

    def test_first_source_wins(self):
        from .market._sources import _first_ok

        result, source = _first_ok([
            (lambda: 'A', 'src_a'),
            (lambda: 'B', 'src_b'),
        ])
        self.assertEqual((result, source), ('A', 'src_a'))

    def test_falls_back_to_second_source(self):
        from .market._sources import _first_ok

        calls = []

        def bad():
            calls.append('a')
            raise RuntimeError('502')

        result, source = _first_ok([
            (bad, 'src_a'),
            (lambda: 'B', 'src_b'),
        ])
        self.assertEqual((result, source), ('B', 'src_b'))
        self.assertEqual(calls, ['a'])

    def test_all_fail_returns_none(self):
        from .market._sources import _first_ok

        result, source = _first_ok([
            (lambda: 1 / 0, 'src_x'),
            (lambda: None, 'src_y'),  # empty 也算失败
        ])
        self.assertIsNone(result)
        self.assertIsNone(source)

    def test_cooling_source_is_skipped(self):
        from .market import _sources
        from .market._sources import _first_ok

        _sources._source_mark_fail('src_a', 'boom')
        _sources._source_mark_fail('src_a', 'boom')  # 达到阈值进入冷却
        result, source = _first_ok([
            (lambda: 'A', 'src_a'),
            (lambda: 'B', 'src_b'),
        ])
        self.assertEqual((result, source), ('B', 'src_b'))


class SectorSnapshotFirstTests(TestCase):
    """5d/10d 快照优先：窗口齐全不碰东财；不足时退回东财原生排行。"""

    def test_5d_prefers_snapshot_when_window_complete(self):
        for offset in range(5):
            MarketDailySnapshot.objects.create(
                kind=MarketDailySnapshot.KIND_INDUSTRY_FF,
                trade_date=_BASE - timedelta(days=offset),
                payload=[{'name': '半导体', 'net': 10.0, 'change_pct': None}],
            )
        with patch('stocks.services.is_trading_day', _trading_true), patch(
            'stocks.market.snapshots._expected_latest_date', return_value=_BASE,
        ), patch(
            'stocks.market.sectors.fetch_industry_fund_flow',
        ) as fetch_flow:
            result = market.get_sector_rotation(board='industry', period='5d')

        fetch_flow.assert_not_called()
        self.assertTrue(result['available'])
        self.assertEqual(result['items'][0]['net'], 50.0)
        self.assertIn('MarketDailySnapshot', result['meta']['source'])

    def test_5d_falls_back_to_upstream_when_snapshot_insufficient(self):
        upstream = [
            {'name': '半导体', 'net': 100.0, 'inflow': None, 'outflow': None,
             'change_pct': 1.0, 'leader': None, 'leader_pct': None},
        ]
        with patch('stocks.services.is_trading_day', _trading_true), patch(
            'stocks.market.snapshots._expected_latest_date', return_value=_BASE,
        ), patch(
            'stocks.market.sectors.fetch_industry_fund_flow',
            return_value=upstream,
        ) as fetch_flow:
            result = market.get_sector_rotation(board='industry', period='5d')

        fetch_flow.assert_called_once_with(period='5d')
        self.assertTrue(result['available'])
        self.assertIn('stock_sector_fund_flow_rank', result['meta']['source'])

    def test_5d_upstream_used_for_non_net_sort(self):
        upstream = [
            {'name': '半导体', 'net': 100.0, 'inflow': None, 'outflow': None,
             'change_pct': 1.0, 'leader': None, 'leader_pct': None},
        ]
        with patch('stocks.services.is_trading_day', _trading_true), patch(
            'stocks.market.snapshots._expected_latest_date', return_value=_BASE,
        ), patch(
            'stocks.market.sectors.fetch_industry_fund_flow',
            return_value=upstream,
        ) as fetch_flow:
            result = market.get_sector_rotation(
                board='industry', period='5d', sort='change_pct', order='desc',
            )

        fetch_flow.assert_called_once_with(period='5d')
        self.assertTrue(result['available'])


class EtfHistSourceRoutingTests(SimpleTestCase):
    """ETF 历史多源路由：东财优先，失败切新浪；meta 如实标注实际来源。"""

    def setUp(self):
        market._cache.clear()
        from .market import _sources
        _sources._source_state.clear()

    @patch('stocks.market.etf._normalized_etf_items')
    @patch('stocks.market.etf._fetch_etf_spot_df')
    def test_em_source_used_when_available(self, fetch_spot, normalized):
        normalized.return_value = [{
            'code': '510300', 'name': '沪深300ETF', 'exchange': 'SH',
            'share': 100, 'data_date': '2026-09-04',
        }]
        em_df = pd.DataFrame([
            {'日期': '2026-09-01', '开盘': 4.0, '收盘': 4.1, '最高': 4.2,
             '最低': 3.9, '成交量': 1000, '成交额': 4100000, '涨跌幅': 1.2, '换手率': 0.5},
        ])
        with patch('akshare.fund_etf_hist_em', return_value=em_df):
            data = market.get_etf_detail('510300', '1w')

        self.assertEqual(data['history']['meta']['source'], 'akshare.em_etf_hist')
        self.assertEqual(data['history']['count'], 1)
        self.assertEqual(data['history']['items'][0]['turnover'], 4100000)

    @patch('stocks.market.etf._normalized_etf_items')
    @patch('stocks.market.etf._fetch_etf_spot_df')
    def test_sina_fallback_when_em_fails(self, fetch_spot, normalized):
        normalized.return_value = [{
            'code': '510300', 'name': '沪深300ETF', 'exchange': 'SH',
            'share': 100, 'data_date': '2026-09-04',
        }]

        def em_boom(**kwargs):
            raise RuntimeError('502')

        sina_df = pd.DataFrame([
            {'date': '2026-09-01', 'open': 4.0, 'high': 4.2, 'low': 3.9,
             'close': 4.1, 'volume': 1000},
            {'date': '2026-09-02', 'open': 4.1, 'high': 4.3, 'low': 4.0,
             'close': 4.2, 'volume': 1100},
        ])
        with patch('akshare.fund_etf_hist_em', em_boom), patch(
            'akshare.fund_etf_hist_sina', return_value=sina_df,
        ) as sina:
            data = market.get_etf_detail('510300', '1w')

        sina.assert_called_once_with(symbol='sh510300')
        self.assertEqual(data['history']['meta']['source'], 'akshare.sina_etf_hist')
        self.assertTrue(data['history']['available'])
        self.assertEqual(data['history']['count'], 2)
        # 新浪无成交额/涨跌幅/换手率，如实为 None（不推算凑数）
        item = data['history']['items'][0]
        self.assertEqual(item['close'], 4.1)
        self.assertIsNone(item['turnover'])
        self.assertIsNone(item['change_pct'])
        self.assertIsNone(item['turnover_rate'])

    @patch('stocks.market.etf._normalized_etf_items')
    @patch('stocks.market.etf._fetch_etf_spot_df')
    def test_hist_unavailable_when_all_sources_fail(self, fetch_spot, normalized):
        normalized.return_value = [{
            'code': '510300', 'name': '沪深300ETF', 'exchange': 'SH',
            'share': 100, 'data_date': '2026-09-04',
        }]
        with patch('akshare.fund_etf_hist_em', side_effect=RuntimeError('502')), patch(
            'akshare.fund_etf_hist_sina', side_effect=RuntimeError('timeout'),
        ):
            data = market.get_etf_detail('510300', '1w')

        self.assertFalse(data['history']['available'])
        self.assertIsNone(data['price_performance']['return_5d'])


class StockGroupApiTests(TestCase):
    def test_group_crud_assign_and_ungroup_on_delete(self):
        stock = Stock.objects.create(code='600000', name='浦发银行')

        response = self.client.post('/api/stock-groups/', json.dumps({'name': '白马'}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        group_id = response.data['id']

        # 重名 409
        response = self.client.post('/api/stock-groups/', json.dumps({'name': '白马'}), content_type='application/json')
        self.assertEqual(response.status_code, 409)

        # 把股票划入分组
        response = self.client.patch(f'/api/stocks/{stock.id}/', json.dumps({'group': group_id}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['group'], group_id)

        # 列表带活跃股票计数；dashboard 行携带分组信息
        self.assertEqual(self.client.get('/api/stock-groups/').data[0]['stock_count'], 1)
        dashboard_row = self.client.get('/api/dashboard/').data[0]
        self.assertEqual(dashboard_row['group_id'], group_id)
        self.assertEqual(dashboard_row['group_name'], '白马')

        # 重命名
        response = self.client.patch(f'/api/stock-groups/{group_id}/', json.dumps({'name': '价值'}), content_type='application/json')
        self.assertEqual(response.data['name'], '价值')

        # 删除分组 → 股票自动回到未分组
        response = self.client.delete(f'/api/stock-groups/{group_id}/')
        self.assertEqual(response.status_code, 204)
        dashboard_row = self.client.get('/api/dashboard/').data[0]
        self.assertIsNone(dashboard_row['group_id'])

    def test_group_name_required(self):
        response = self.client.post('/api/stock-groups/', json.dumps({'name': '  '}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
