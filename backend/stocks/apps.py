from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class StocksConfig(AppConfig):
    name = 'stocks'
    verbose_name = '股票监控'

    def ready(self):
        """Django 启动时尝试启动 APScheduler（文件锁保证单实例）"""
        try:
            from .scheduler import start
            start()
        except Exception as e:
            logger.warning(f"APScheduler 启动失败: {e}")
