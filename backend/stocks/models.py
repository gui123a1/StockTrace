from django.db import models


class AiProvider(models.Model):
    """LLM 服务商配置（OpenAI 兼容协议，一套客户端通吃 DeepSeek/Kimi/Qwen/GLM 等）

    api_key 落库前用 DJANGO_SECRET_KEY 派生密钥加密（stocks/ai/crypto.py），
    序列化输出只回尾四位脱敏。
    """
    name = models.CharField('名称', max_length=50)
    base_url = models.CharField('接口地址', max_length=200,
                                help_text='OpenAI 兼容 base_url，如 https://api.deepseek.com')
    api_key_encrypted = models.TextField('加密的 API Key')
    model = models.CharField('模型名', max_length=100)
    is_enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'AI 服务商'
        verbose_name_plural = 'AI 服务商'
        ordering = ['-is_enabled', 'id']

    def __str__(self):
        return f"{self.name} ({self.model})"


class AiCallLog(models.Model):
    """AI 调用流水：用于同股冷却与每日调用上限节流（防 Basic Auth 泄露后额度被烧）"""
    PURPOSE_ANALYSIS = 'analysis'
    PURPOSE_SCREENER_TRANSLATE = 'screener_translate'
    PURPOSE_SCREENER_COMMENT = 'screener_comment'
    PURPOSE_CHOICES = [
        (PURPOSE_ANALYSIS, '个股分析'),
        (PURPOSE_SCREENER_TRANSLATE, '选股条件翻译'),
        (PURPOSE_SCREENER_COMMENT, '选股结果点评'),
    ]

    provider = models.ForeignKey(
        AiProvider, on_delete=models.SET_NULL, null=True, verbose_name='服务商'
    )
    stock = models.ForeignKey(
        'Stock', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='股票'
    )
    purpose = models.CharField('用途', max_length=30, choices=PURPOSE_CHOICES)
    success = models.BooleanField('成功', default=True)
    prompt_tokens = models.IntegerField('输入 tokens', null=True, blank=True)
    completion_tokens = models.IntegerField('输出 tokens', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = 'AI 调用记录'
        verbose_name_plural = 'AI 调用记录'
        ordering = ['-created_at']


class StockGroup(models.Model):
    """自选股分组；股票可不分组（group 为空）。删除分组时股票自动变回未分组。"""
    name = models.CharField('分组名称', max_length=50, unique=True)
    order = models.IntegerField('显示顺序', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '自选分组'
        verbose_name_plural = '自选分组'
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


class Stock(models.Model):
    """关注的股票"""
    code = models.CharField('股票代码', max_length=10, unique=True)
    name = models.CharField('股票名称', max_length=50, blank=True, default='')
    is_active = models.BooleanField('是否监控中', default=True)
    group = models.ForeignKey(
        StockGroup, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stocks', verbose_name='分组',
    )
    # 可选持仓成本：填了才参与看板盈亏统计（None 表示纯观察，不算钱）
    cost_price = models.DecimalField('成本价', max_digits=10, decimal_places=3, null=True, blank=True)
    quantity = models.IntegerField('持股数(股)', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '关注股票'
        verbose_name_plural = '关注股票'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} {self.name}"


class MarketDailySnapshot(models.Model):
    """市场日度快照：收盘后把当日关键横截面落库一行，用于多日趋势指标。

    数据诚信：只存上游当日真实返回；某天上游不可用就没有该行，
    多日指标按「窗口内快照齐全才算数」计算，绝不拿 0 或旧值补天。
    """
    KIND_INDUSTRY_FF = 'industry_ff'
    KIND_CONCEPT_FF = 'concept_ff'
    KIND_ETF_SHARE = 'etf_share'
    KIND_MARKET_FF = 'market_ff'
    KIND_CHOICES = [
        (KIND_INDUSTRY_FF, '行业资金流'),
        (KIND_CONCEPT_FF, '概念资金流'),
        (KIND_ETF_SHARE, 'ETF份额'),
        (KIND_MARKET_FF, '大盘主力资金流'),
    ]

    kind = models.CharField('快照类型', max_length=30, choices=KIND_CHOICES)
    trade_date = models.DateField('交易日期')
    payload = models.JSONField('快照数据')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '市场日度快照'
        verbose_name_plural = '市场日度快照'
        unique_together = ['kind', 'trade_date']
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.kind} {self.trade_date}"


class PriceAlert(models.Model):
    """自选股价格提醒规则（收盘汇总与盘中任务顺带评估，无独立轮询）"""
    PRICE_ABOVE = 'price_above'
    PRICE_BELOW = 'price_below'
    DAILY_PCT_ABOVE = 'daily_pct_above'
    DAILY_PCT_BELOW = 'daily_pct_below'
    RULE_CHOICES = [
        (PRICE_ABOVE, '价格上穿'),
        (PRICE_BELOW, '价格下穿'),
        (DAILY_PCT_ABOVE, '日涨幅达到'),
        (DAILY_PCT_BELOW, '日跌幅达到'),
    ]

    stock = models.ForeignKey(
        Stock, on_delete=models.CASCADE, related_name='alerts', verbose_name='股票'
    )
    rule_type = models.CharField('规则类型', max_length=30, choices=RULE_CHOICES)
    threshold = models.DecimalField('阈值', max_digits=12, decimal_places=4)
    note = models.CharField('备注', max_length=100, blank=True, default='')
    is_active = models.BooleanField('启用', default=True)
    last_triggered_at = models.DateTimeField('最近触发时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '价格提醒'
        verbose_name_plural = '价格提醒'
        ordering = ['stock__code', 'id']

    def __str__(self):
        return f"{self.stock.code} {self.get_rule_type_display()} {self.threshold}"


class AlertEvent(models.Model):
    """提醒触发记录；同一规则同一交易日只触发一次（trade_date 去重）"""
    alert = models.ForeignKey(
        PriceAlert, on_delete=models.CASCADE, related_name='events', verbose_name='提醒规则'
    )
    stock = models.ForeignKey(
        Stock, on_delete=models.SET_NULL, null=True, verbose_name='股票'
    )
    message = models.CharField('提醒内容', max_length=200)
    trade_date = models.DateField('触发交易日')
    is_read = models.BooleanField('已读', default=False)
    created_at = models.DateTimeField('触发时间', auto_now_add=True)

    class Meta:
        verbose_name = '提醒记录'
        verbose_name_plural = '提醒记录'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.message} ({self.trade_date})"


class ScreenerPreset(models.Model):
    """条件选股预设：保存结构化条件 spec，供一键重跑（单用户系统，无归属字段）"""
    name = models.CharField('预设名称', max_length=50, unique=True)
    spec = models.JSONField('筛选条件')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '选股预设'
        verbose_name_plural = '选股预设'
        ordering = ['name']

    def __str__(self):
        return self.name


class DailyQuote(models.Model):
    """每日行情数据（含最高/最低点精确时间）"""
    stock = models.ForeignKey(
        Stock, on_delete=models.CASCADE,
        related_name='daily_quotes', verbose_name='股票'
    )
    trade_date = models.DateField('交易日期')

    open_price = models.DecimalField('开盘价', max_digits=10, decimal_places=2)
    close_price = models.DecimalField('收盘价', max_digits=10, decimal_places=2)
    high_price = models.DecimalField('最高价', max_digits=10, decimal_places=2)
    low_price = models.DecimalField('最低价', max_digits=10, decimal_places=2)

    high_time = models.DateTimeField('最高点时间', null=True, blank=True)
    low_time = models.DateTimeField('最低点时间', null=True, blank=True)

    # 计算字段
    open_close_diff = models.DecimalField(
        '收盘-开盘差值', max_digits=10, decimal_places=2
    )
    open_close_pct = models.DecimalField(
        '收盘-开盘百分比', max_digits=8, decimal_places=4
    )
    high_low_diff = models.DecimalField(
        '最高-最低差值', max_digits=10, decimal_places=2
    )
    high_low_pct = models.DecimalField(
        '最高-最低百分比', max_digits=8, decimal_places=4
    )

    # 相对昨收的涨跌
    prev_close = models.DecimalField('昨收价', max_digits=10, decimal_places=2, null=True, blank=True)
    change_diff = models.DecimalField('涨跌额', max_digits=10, decimal_places=2, null=True, blank=True)
    change_pct = models.DecimalField('涨跌幅', max_digits=8, decimal_places=4, null=True, blank=True)

    volume = models.BigIntegerField('成交量', null=True, blank=True)
    turnover = models.DecimalField(
        '成交额', max_digits=15, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = '每日行情'
        verbose_name_plural = '每日行情'
        unique_together = ['stock', 'trade_date']
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.stock.code} {self.trade_date}"

    def compute_derived_fields(self):
        """计算差值和百分比"""
        self.open_close_diff = self.close_price - self.open_price
        self.open_close_pct = (
            self.open_close_diff / self.open_price * 100
            if self.open_price else 0
        )
        self.high_low_diff = self.high_price - self.low_price
        self.high_low_pct = (
            self.high_low_diff / self.low_price * 100
            if self.low_price else 0
        )
        if self.prev_close is not None:
            self.change_diff = self.close_price - self.prev_close
            self.change_pct = (
                self.change_diff / self.prev_close * 100
                if self.prev_close else 0
            )


class MinuteBar(models.Model):
    """分钟K线数据（用于推算最高/最低点精确时间）"""
    stock = models.ForeignKey(
        Stock, on_delete=models.CASCADE,
        related_name='minute_bars', verbose_name='股票'
    )
    datetime = models.DateTimeField('分钟时间戳')
    open = models.DecimalField('开盘价', max_digits=10, decimal_places=2)
    close = models.DecimalField('收盘价', max_digits=10, decimal_places=2)
    high = models.DecimalField('最高价', max_digits=10, decimal_places=2)
    low = models.DecimalField('最低价', max_digits=10, decimal_places=2)
    volume = models.BigIntegerField('成交量')
    turnover = models.DecimalField(
        '成交额', max_digits=15, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = '分钟K线'
        verbose_name_plural = '分钟K线'
        unique_together = ['stock', 'datetime']
        ordering = ['datetime']

    def __str__(self):
        return f"{self.stock.code} {self.datetime}"
