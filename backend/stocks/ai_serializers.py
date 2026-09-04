from rest_framework import serializers
from .models import AiProvider
from .ai.crypto import encrypt_api_key, decrypt_api_key, mask_api_key


class AiProviderSerializer(serializers.ModelSerializer):
    # 读：脱敏尾四位；写：明文 key，只写不读
    api_key_masked = serializers.SerializerMethodField()
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = AiProvider
        fields = [
            'id', 'name', 'base_url', 'model', 'is_enabled',
            'api_key', 'api_key_masked', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_api_key_masked(self, obj):
        try:
            return mask_api_key(decrypt_api_key(obj.api_key_encrypted))
        except ValueError:
            # SECRET_KEY 轮换后旧密文解不开：如实标注而不是假装正常
            return '(无法解密，请重新录入)'

    def validate(self, attrs):
        api_key = attrs.pop('api_key', None)
        if api_key:
            attrs['api_key_encrypted'] = encrypt_api_key(api_key)
        elif self.instance is None and not attrs.get('api_key_encrypted'):
            raise serializers.ValidationError({'api_key': '创建时必须提供 API Key'})
        return attrs
