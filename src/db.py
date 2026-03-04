from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from src.config import settings
from src.models.signal import Signal
from src.models.signal_run import SignalRun
from src.models.app_config import AppConfig
from src.models.app_event import AppEvent
from src.models.user import User


async def init_db():
    client = AsyncIOMotorClient(settings.mongo_uri)
    await init_beanie(
        database=client[settings.mongo_db],
        document_models=[Signal, SignalRun, AppConfig, AppEvent, User],
    )
