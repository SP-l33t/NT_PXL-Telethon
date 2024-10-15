from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str
    GLOBAL_CONFIG_PATH: str = "TG_FARM"

    REF_ID: str = "f525256526"
    SQUAD_ID: str = None

    SLEEP_TIME: list[int] = [2700, 4200]
    AUTO_TASK: bool = True
    TASKS_TO_DO: list[str] = ["paint20pixels", "x:notpixel", "x:notcoin", "channel:notcoin", "channel:notpixel_channel", "joinSquad", "jettonTask"]
    AUTO_DRAW: bool = True
    JOIN_TG_CHANNELS: bool = False
    CLAIM_REWARD: bool = True
    AUTO_UPGRADE: bool = True
    IGNORED_BOOSTS: list[str] = ['paintReward']
    NIGHT_MODE: bool = True
    NIGHT_TIME: list[int] = [0, 7] #UTC HOURS
    NIGHT_CHECKING: list[int] = [3600, 7200]
    ENERGY_LIMIT_MAX_LEVEL: int = 7
    PAINT_REWARD_MAX_LEVEL: int = 1
    RECHARGE_SPEED_MAX_LEVEL: int = 11
    POINTS_3X: bool = False

    RANDOM_SESSION_START_DELAY: int = 180

    SESSIONS_PER_PROXY: int = 1
    USE_PROXY_FROM_FILE: bool = True
    DISABLE_PROXY_REPLACE: bool = False
    USE_PROXY_CHAIN: bool = False

    DEVICE_PARAMS: bool = False

    DEBUG_LOGGING: bool = False


settings = Settings()
