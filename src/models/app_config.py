from beanie import Document, PydanticObjectId


class AppConfig(Document):
    user_id: PydanticObjectId
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    class Settings:
        name = "app_config"

    @classmethod
    async def get_for_user(cls, user_id: PydanticObjectId) -> "AppConfig":
        config = await cls.find_one(cls.user_id == user_id)
        if not config:
            config = cls(user_id=user_id)
            await config.insert()
        return config
