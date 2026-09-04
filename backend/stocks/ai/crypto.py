"""API Key 加密存储：用 DJANGO_SECRET_KEY 派生 Fernet 密钥做对称加密。

脱离本机 SECRET_KEY 无法还原 Key；SECRET_KEY 轮换后旧密文解不开，
需在设置页重新录入。
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    secret = settings.SECRET_KEY
    if not secret:
        raise ImproperlyConfigured('SECRET_KEY 未设置，无法加解密 API Key')
    digest = hashlib.sha256(secret.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(plain: str) -> str:
    return _fernet().encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt_api_key(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        raise ValueError('API Key 解密失败（SECRET_KEY 可能已轮换，请重新录入）') from exc


def mask_api_key(plain: str) -> str:
    """脱敏展示：只回尾四位"""
    if len(plain) <= 4:
        return '****'
    return '****' + plain[-4:]
