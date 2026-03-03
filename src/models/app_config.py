from beanie import Document


class AppConfig(Document):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    class Settings:
        name = "app_config"

    @classmethod
    async def get_singleton(cls) -> "AppConfig":
        config = await cls.find_one()
        if not config:
            config = cls()
            await config.insert()
        return config
