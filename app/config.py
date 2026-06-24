from app.database import get_setting

class DynamicConfig:
    @property
    def tg_token(self):
        return get_setting('tg_token', '')

    @property
    def emby_server_url(self):
        return get_setting('emby_server_url', '')

    @property
    def emby_api_key(self):
        return get_setting('emby_api_key', '')

    @property
    def emby_proxy_url(self):
        return get_setting('emby_proxy_url', '')

    @property
    def allowed_chat_ids(self):
        val = get_setting('allowed_chat_id', '')
        if not val:
            return []
        ids = []
        for x in val.replace('，', ',').split(','):
            x = x.strip()
            if x:
                try:
                    ids.append(int(x))
                except ValueError:
                    pass
        return ids

    @property
    def template_user_id(self):
        return get_setting('template_user_id', '')

    @property
    def policy_json(self):
        return get_setting('policy_json', '{}')

# 全局单一配置访问对象
config = DynamicConfig()
