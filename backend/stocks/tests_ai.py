"""AI 功能测试：Key 加密、Provider 序列化脱敏、节流、条件选股引擎、端点行为"""
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import AiCallLog, AiProvider, DailyQuote, Stock
from .ai.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from .ai.llm import LlmError
from .ai.screener import ConditionError, run_screener
from .ai.throttle import DAILY_LIMIT, check_throttle, log_call


class CryptoTests(TestCase):
    def test_roundtrip(self):
        token = encrypt_api_key('sk-test-1234')
        self.assertNotIn('sk-test-1234', token)
        self.assertEqual(decrypt_api_key(token), 'sk-test-1234')

    def test_mask_keeps_last_four(self):
        self.assertEqual(mask_api_key('sk-abcdef1234'), '****1234')
        self.assertEqual(mask_api_key('1234'), '****')


def _mock_chat_json(spec):
    """构造 LlmClient.chat_json 的 mock 返回（chat_json 已完成 JSON 解析）"""
    return lambda messages, **kwargs: (spec, {})


class ScreenerEngineTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code='000001', name='测试银行')
        DailyQuote.objects.create(
            stock=self.stock, trade_date=date(2026, 9, 4),
            open_price=Decimal('10.00'), close_price=Decimal('10.50'),
            high_price=Decimal('10.80'), low_price=Decimal('9.90'),
            open_close_diff=Decimal('0.50'), open_close_pct=Decimal('5.0000'),
            high_low_diff=Decimal('0.90'), high_low_pct=Decimal('9.0909'),
            prev_close=Decimal('10.00'), change_diff=Decimal('0.50'),
            change_pct=Decimal('5.0000'), volume=100000, turnover=Decimal('105000000'),
        )

    def test_condition_match(self):
        rows = run_screener({'logic': 'all', 'conditions': [
            {'field': 'change_pct', 'op': 'gt', 'value': 3},
        ]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], '000001')

    def test_condition_no_match(self):
        rows = run_screener({'logic': 'all', 'conditions': [
            {'field': 'change_pct', 'op': 'gt', 'value': 10},
        ]})
        self.assertEqual(rows, [])

    def test_between(self):
        rows = run_screener({'logic': 'all', 'conditions': [
            {'field': 'turnover', 'op': 'between', 'value': [50000000, 200000000]},
        ]})
        self.assertEqual(len(rows), 1)

    def test_any_logic(self):
        rows = run_screener({'logic': 'any', 'conditions': [
            {'field': 'change_pct', 'op': 'gt', 'value': 10},
            {'field': 'change_pct', 'op': 'lt', 'value': 1},
            {'field': 'change_pct', 'op': 'gt', 'value': 3},
        ]})
        self.assertEqual(len(rows), 1)

    def test_invalid_field_raises(self):
        with self.assertRaises(ConditionError):
            run_screener({'logic': 'all', 'conditions': [
                {'field': 'pe', 'op': 'gt', 'value': 10},
            ]})

    def test_inactive_stock_excluded(self):
        self.stock.is_active = False
        self.stock.save()
        rows = run_screener({'logic': 'all', 'conditions': [
            {'field': 'change_pct', 'op': 'gt', 'value': 0},
        ]})
        self.assertEqual(rows, [])

    def test_null_field_is_not_treated_as_zero(self):
        """涨跌幅为 null 的股票不应命中 change_pct 相关条件"""
        stock2 = Stock.objects.create(code='000002', name='无涨跌')
        DailyQuote.objects.create(
            stock=stock2, trade_date=date(2026, 9, 4),
            open_price=Decimal('10.00'), close_price=Decimal('10.00'),
            high_price=Decimal('10.00'), low_price=Decimal('10.00'),
            open_close_diff=Decimal('0'), open_close_pct=Decimal('0'),
            high_low_diff=Decimal('0'), high_low_pct=Decimal('0'),
            prev_close=None, change_diff=None, change_pct=None,
        )
        rows = run_screener({'logic': 'all', 'conditions': [
            {'field': 'change_pct', 'op': 'gt', 'value': -100},
        ]})
        self.assertEqual([r['code'] for r in rows], ['000001'])


class ThrottleTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code='000001', name='测试')

    def test_cooldown_blocks_second_call(self):
        log_call('analysis', stock=self.stock)
        allowed, reason = check_throttle('analysis', stock=self.stock)
        self.assertFalse(allowed)
        self.assertIn('秒内', reason)

    def test_cooldown_expires(self):
        log_call('analysis', stock=self.stock)
        AiCallLog.objects.update(
            created_at=timezone.now() - timedelta(seconds=120)
        )
        allowed, _ = check_throttle('analysis', stock=self.stock)
        self.assertTrue(allowed)

    def test_daily_limit_blocks(self):
        for _ in range(DAILY_LIMIT):
            log_call('screener_comment')
        allowed, reason = check_throttle('screener_comment')
        self.assertFalse(allowed)
        self.assertIn('上限', reason)


class AiProviderApiTests(TestCase):
    def test_create_masks_key_and_stores_encrypted(self):
        response = self.client.post('/api/ai-providers/', {
            'name': 'DeepSeek', 'base_url': 'https://api.deepseek.com',
            'model': 'deepseek-chat', 'api_key': 'sk-secret-9999',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['api_key_masked'], '****9999')
        self.assertNotIn('api_key', response.data)
        provider = AiProvider.objects.get()
        self.assertNotIn('sk-secret-9999', provider.api_key_encrypted)

    def test_update_without_key_keeps_old(self):
        self.client.post('/api/ai-providers/', {
            'name': 'A', 'base_url': 'https://a.com', 'model': 'm',
            'api_key': 'sk-old-1111',
        }, content_type='application/json')
        pid = AiProvider.objects.get().id
        response = self.client.patch(
            f'/api/ai-providers/{pid}/', {'model': 'm2'},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        provider = AiProvider.objects.get()
        self.assertEqual(decrypt_api_key(provider.api_key_encrypted), 'sk-old-1111')
        self.assertEqual(provider.model, 'm2')

    def test_list_never_leaks_plaintext(self):
        self.client.post('/api/ai-providers/', {
            'name': 'A', 'base_url': 'https://a.com', 'model': 'm',
            'api_key': 'sk-plain-2222',
        }, content_type='application/json')
        response = self.client.get('/api/ai-providers/')
        body = json.dumps(response.json())
        self.assertNotIn('sk-plain-2222', body)
        self.assertIn('****2222', body)


class AiEndpointTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code='000001', name='测试')
        DailyQuote.objects.create(
            stock=self.stock, trade_date=date(2026, 9, 4),
            open_price=Decimal('10.00'), close_price=Decimal('10.50'),
            high_price=Decimal('10.80'), low_price=Decimal('9.90'),
            open_close_diff=Decimal('0.50'), open_close_pct=Decimal('5.0000'),
            high_low_diff=Decimal('0.90'), high_low_pct=Decimal('9.0909'),
            prev_close=Decimal('10.00'), change_diff=Decimal('0.50'),
            change_pct=Decimal('5.0000'), volume=100000, turnover=Decimal('105000000'),
        )
        self.provider = AiProvider.objects.create(
            name='Mock', base_url='https://mock.local', model='mock-1',
            api_key_encrypted=encrypt_api_key('sk-mock-3333'),
        )

    def test_analysis_requires_provider_configured(self):
        self.provider.is_enabled = False
        self.provider.save()
        response = self.client.post(f'/api/stocks/{self.stock.id}/ai-analysis/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('未配置', response.data['detail'])

    @patch('stocks.ai.views.LlmClient')
    def test_analysis_success_with_disclaimer(self, mock_client_cls):
        mock_client_cls.return_value.provider = self.provider
        mock_client_cls.return_value.chat.return_value = ('看起来不错', {})
        response = self.client.post(f'/api/stocks/{self.stock.id}/ai-analysis/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['analysis'], '看起来不错')
        self.assertEqual(response.data['disclaimer'], 'AI 生成，非投资建议')

    @patch('stocks.ai.views.LlmClient')
    def test_analysis_upstream_error_is_honest(self, mock_client_cls):
        mock_client_cls.return_value.provider = self.provider
        mock_client_cls.return_value.chat.side_effect = LlmError('上游挂了')
        response = self.client.post(f'/api/stocks/{self.stock.id}/ai-analysis/')
        self.assertEqual(response.status_code, 502)
        self.assertIn('上游挂了', response.data['detail'])

    def test_screener_invalid_condition_returns_400(self):
        response = self.client.post('/api/screener/', {
            'logic': 'all', 'conditions': [{'field': 'pe', 'op': 'gt', 'value': 10}],
        }, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_screener_success(self):
        response = self.client.post('/api/screener/', {
            'logic': 'all', 'conditions': [{'field': 'change_pct', 'op': 'gt', 'value': 3}],
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

    @patch('stocks.ai.views.LlmClient')
    def test_screener_ai_translates_and_executes(self, mock_client_cls):
        spec = {'logic': 'all', 'conditions': [
            {'field': 'change_pct', 'op': 'gt', 'value': 3},
        ]}
        mock_client_cls.return_value.provider = self.provider
        mock_client_cls.return_value.chat_json.side_effect = _mock_chat_json(spec)
        response = self.client.post('/api/screener/ai/', {
            'query': '涨3个点以上',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['conditions'], spec)

    @patch('stocks.ai.views.LlmClient')
    def test_screener_ai_rejects_bad_translation(self, mock_client_cls):
        bad_spec = {'logic': 'all', 'conditions': [
            {'field': '市盈率', 'op': 'gt', 'value': 10},
        ]}
        mock_client_cls.return_value.provider = self.provider
        mock_client_cls.return_value.chat_json.side_effect = _mock_chat_json(bad_spec)
        response = self.client.post('/api/screener/ai/', {
            'query': '低市盈率',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('无法执行', response.data['detail'])

    @patch('stocks.ai.views.LlmClient')
    def test_comment_success_with_disclaimer(self, mock_client_cls):
        mock_client_cls.return_value.provider = self.provider
        mock_client_cls.return_value.chat.return_value = ('强势', {})
        rows = run_screener({'logic': 'all', 'conditions': [
            {'field': 'change_pct', 'op': 'gt', 'value': 3},
        ]})
        response = self.client.post('/api/screener/ai/comment/', {
            'query': '涨3个点以上', 'results': rows,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['comment'], '强势')
        self.assertEqual(response.data['disclaimer'], 'AI 生成，非投资建议')

    def test_comment_requires_results(self):
        response = self.client.post('/api/screener/ai/comment/', {
            'query': 'x', 'results': [],
        }, content_type='application/json')
        self.assertEqual(response.status_code, 400)
