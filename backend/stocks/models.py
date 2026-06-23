from django.db import models


class Stock(models.Model):
    """关注的股票"""
    code = models.CharField('股票代码', max_length=10, unique=True)
    name = models.CharField('股票名称', max_length=50, blank=True, default='')
    is_active = models.BooleanField('是否监控中', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '关注股票'
        verbose_name_plural = '关注股票'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} {self.name}"


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
