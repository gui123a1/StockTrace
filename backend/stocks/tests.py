from datetime import datetime
from time import time
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase
from django.utils import timezone

from . import market


class MarketParsingTests(SimpleTestCase):
    def setUp(self):
        market._cache.clear()

    def test_etf_normalization_and_scope(self):
        equity = market._etf_row_to_item(pd.Series({
            '代码': '510300', '名称': '沪深300ETF', '最新价': 4.2,
            '最新份额': 100000000, '成交额': 200000000,
            '总市值': 420000000, '主力净流入-净额': 1200000,
            'IOPV实时估值': 4.19, '昨收': 4.1,
        }))
        bond = market._etf_row_to_item(pd.Series({'代码': '511010', '名称': '国债ETF'}))

        self.assertTrue(equity['scope_match'])
        self.assertEqual(equity['exchange'], 'SH')
        self.assertEqual(equity['iopv'], 4.19)
        self.assertFalse(bond['scope_match'])

    def test_sector_amounts_are_converted_from_yi_to_yuan(self):
        frame = pd.DataFrame([{
            '行业': '科技', '净额': 12.5, '流入资金': 20, '流出资金': 7.5,
            '行业-涨跌幅': 2.1, '领涨股': '示例', '领涨股-涨跌幅': 8.2,
        }])
        item = market._parse_fund_flow_table(frame, ['行业'])[0]
        self.assertEqual(item['net'], 1_250_000_000)
        self.assertEqual(item['inflow'], 2_000_000_000)
        self.assertEqual(item['outflow'], 750_000_000)

    def test_sector_parser_deduplicates_names_by_stronger_net_amount(self):
        frame = pd.DataFrame([
            {'行业': 'AI', '净额': 10, '流入资金': 20, '流出资金': 10},
            {'行业': 'AI', '净额': -15, '流入资金': 5, '流出资金': 20},
            {'行业': '算力', '净额': 8, '流入资金': 10, '流出资金': 2},
        ])
        items = market._parse_fund_flow_table(frame, ['行业'])

        self.assertEqual(len(items), 2)
        self.assertEqual(next(item for item in items if item['name'] == 'AI')['net'], -1_500_000_000)

    @patch('stocks.market.etf._fetch_etf_spot_df')
    def test_etf_radar_filters_sorts_and_paginates(self, fetch_spot):
        fetch_spot.return_value = pd.DataFrame([
            {'代码': '510300', '名称': '沪深300ETF', '最新份额': 300, '成交额': 1000, '主力净流入-净额': 10},
            {'代码': '159915', '名称': '创业板ETF', '最新份额': 200, '成交额': 2000, '主力净流入-净额': -5},
            {'代码': '511010', '名称': '国债ETF', '最新份额': 400, '成交额': 3000, '主力净流入-净额': 1},
        ])
        data = market.get_etf_share_radar(scope='equity_broad', rank='turnover', page=1, page_size=1)

        self.assertEqual(data['scope']['all_count'], 3)
        self.assertEqual(data['scope']['equity_broad_count'], 2)
        self.assertEqual(data['pagination']['total'], 2)
        self.assertEqual(data['items'][0]['code'], '159915')
        self.assertFalse(data['supported_metrics']['share_change_5d'])

    @patch('stocks.market.etf._fetch_etf_spot_df')
    def test_etf_radar_summary_uses_filtered_full_result_and_sort_is_stable(self, fetch_spot):
        fetch_spot.return_value = pd.DataFrame([
            {'代码': '510500', '名称': '中证500ETF', '成交额': 2000, '主力净流入-净额': 20},
            {'代码': '510300', '名称': '沪深300ETF', '成交额': 2000, '主力净流入-净额': 10},
            {'代码': '159915', '名称': '创业板ETF', '成交额': 500, '主力净流入-净额': -5},
        ])
        data = market.get_etf_share_radar(
            scope='equity_broad', rank='turnover', min_turnover=1000,
            page=1, page_size=1,
        )

        self.assertEqual(data['pagination']['total'], 2)
        self.assertEqual(data['summary']['count'], 2)
        self.assertEqual(data['summary']['total_turnover'], 4000)
        self.assertEqual(data['summary']['total_main_net'], 30)
        self.assertEqual(data['items'][0]['code'], '510300')

    def test_sector_payload_has_current_day_analytics(self):
        items = [
            {'name': 'A', 'net': 100, 'inflow': 120, 'outflow': 20, 'change_pct': 1, 'leader': 'A1', 'leader_pct': 3},
            {'name': 'B', 'net': 50, 'inflow': 70, 'outflow': 20, 'change_pct': -1, 'leader': 'B1', 'leader_pct': 2},
            {'name': 'C', 'net': -80, 'inflow': 20, 'outflow': 100, 'change_pct': 1, 'leader': 'C1', 'leader_pct': 2},
        ]
        data = market._sector_payload(items, 'industry')

        self.assertEqual(data['summary']['sample_count'], 3)
        self.assertEqual(data['summary']['inflow_count'], 2)
        self.assertEqual(data['summary']['outflow_count'], 1)
        self.assertEqual(data['summary']['neutral_count'], 0)
        self.assertEqual(data['unavailable_periods'], ['5d', '10d', '20d'])
        self.assertEqual([item['name'] for item in data['divergences']], ['C', 'B'])

    @patch('stocks.market.etf._fetch_etf_spot_df')
    def test_national_etf_is_explicitly_watchlist_not_holdings(self, fetch_spot):
        fetch_spot.return_value = pd.DataFrame([{
            '代码': '510300', '名称': '沪深300ETF', '最新价': 4.2,
            '最新份额': 100, '总市值': 420, '数据日期': '2026-07-31',
        }])

        data = market.get_national_team_etfs()

        self.assertEqual(data['mode'], 'watchlist')
        self.assertFalse(data['official_disclosure_available'])
        self.assertFalse(data['watchlist_definition']['is_official_holding'])
        self.assertEqual(data['meta']['source_data_date'], '2026-07-31')
        forbidden = {'holder', 'weight', 'holding_shares', 'holding_cost', 'institution'}
        for item in data['items']:
            self.assertTrue(forbidden.isdisjoint(item))

    @patch('stocks.market.etf._etf_history')
    @patch('stocks.market.etf._normalized_etf_items')
    def test_etf_detail_returns_price_history_only(self, normalized, history):
        normalized.return_value = [{
            'code': '510300', 'name': '沪深300ETF', 'exchange': 'SH',
            'share': 100, 'data_date': '2026-07-31',
        }]
        history.return_value = [
            {'date': f'2026-01-{i:02d}', 'close': float(i)} for i in range(1, 22)
        ]
        data = market.get_etf_detail('510300', '3m')

        self.assertEqual(data['share_metrics']['availability'], 'latest_only')
        self.assertIsNotNone(data['price_performance']['return_5d'])
        self.assertEqual(data['history']['interval'], '1d')
        self.assertTrue(data['history']['available'])
        self.assertEqual(data['history']['count'], 21)
        self.assertEqual(data['history']['start_date'], '2026-01-01')
        self.assertEqual(data['history']['end_date'], '2026-01-21')

    @patch('stocks.market.etf._etf_history', return_value=[])
    @patch('stocks.market.etf._normalized_etf_items')
    def test_etf_detail_keeps_quote_when_history_is_unavailable(self, normalized, history):
        normalized.return_value = [{
            'code': '510300', 'name': '沪深300ETF', 'exchange': 'SH',
            'share': 100, 'data_date': '2026-07-31',
        }]

        data = market.get_etf_detail('510300', '3m')

        self.assertTrue(data['meta']['available'])
        self.assertFalse(data['history']['available'])
        self.assertEqual(data['history']['meta']['cache_status'], 'unavailable')
        self.assertIsNone(data['history']['start_date'])
        self.assertIsNone(data['price_performance']['return_5d'])


class MarketCacheFreshnessTests(SimpleTestCase):
    """交易日历感知的新鲜度：TTL 过期但已覆盖最近收盘时，非交易时段不重拉。"""

    def test_stale_entry_fresh_when_covers_last_session_close(self):
        close = timezone.make_aware(datetime(2026, 8, 28, 15, 0))
        with patch('stocks.market._cache._calendar_enabled', return_value=True), \
             patch('stocks.market._cache._data_changing_now', return_value=False), \
             patch('stocks.market._cache._last_session_close', return_value=close):
            self.assertTrue(market._is_fresh(close.timestamp() + 60, ttl=60))
            self.assertFalse(market._is_fresh(close.timestamp() - 60, ttl=60))

    def test_ttl_applies_while_data_changing(self):
        with patch('stocks.market._cache._calendar_enabled', return_value=True), \
             patch('stocks.market._cache._data_changing_now', return_value=True):
            self.assertFalse(market._is_fresh(time() - 600, ttl=60))
            self.assertTrue(market._is_fresh(time() - 10, ttl=60))


class MarketApiValidationTests(SimpleTestCase):
    def test_invalid_etf_scope_returns_400(self):
        response = self.client.get('/api/market/etf-radar/?scope=bad')
        self.assertEqual(response.status_code, 400)

    def test_invalid_etf_query_parameters_return_400(self):
        for query in (
            'rank=unknown', 'sort=raw_dataframe_column', 'order=sideways',
            'page=0', 'page=abc', 'min_turnover=-1', 'min_turnover=abc',
        ):
            with self.subTest(query=query):
                response = self.client.get(f'/api/market/etf-radar/?{query}')
                self.assertEqual(response.status_code, 400)

    def test_invalid_sector_query_parameters_return_400(self):
        for query in ('board=bad', 'sort=bad', 'order=bad', 'page_size=0'):
            with self.subTest(query=query):
                response = self.client.get(f'/api/market/sectors/?{query}')
                self.assertEqual(response.status_code, 400)

    @patch('stocks.market.etf._fetch_etf_spot_df')
    def test_etf_radar_api_accepts_filters_and_caps_page_size(self, fetch_spot):
        fetch_spot.return_value = pd.DataFrame([
            {'代码': '510300', '名称': '沪深300ETF', '成交额': 2_000_000_000, '最新份额': 100},
            {'代码': '159915', '名称': '创业板ETF', '成交额': 500_000_000, '最新份额': 80},
        ])
        response = self.client.get(
            '/api/market/etf-radar/?scope=equity_broad&rank=turnover&q=300&'
            'min_turnover=1000000000&page=1&page_size=999'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['page_size'], 100)
        self.assertEqual(response.data['pagination']['total'], 1)
        self.assertEqual(response.data['items'][0]['code'], '510300')

    def test_invalid_etf_code_returns_400(self):
        response = self.client.get('/api/market/etfs/abc/')
        self.assertEqual(response.status_code, 400)

    def test_invalid_etf_range_returns_400(self):
        response = self.client.get('/api/market/etfs/510300/?range=5y')
        self.assertEqual(response.status_code, 400)

    def test_invalid_sector_page_returns_400(self):
        response = self.client.get('/api/market/sectors/?page=0')
        self.assertEqual(response.status_code, 400)
