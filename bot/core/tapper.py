import aiohttp
import asyncio
import os
import json
from urllib.parse import unquote, quote
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from datetime import datetime, timedelta, time as dtime
from random import randint, uniform
from time import time

from opentele.tl import TelegramClient
from telethon.errors import *
from telethon.types import InputBotAppShortName, InputNotifyPeer, InputPeerNotifySettings, InputUser
from telethon.functions import messages, account, channels

from bot.config import settings
from bot.utils import logger, log_error, proxy_utils, config_utils, AsyncInterProcessLock, CONFIG_PATH
from bot.exceptions import InvalidSession
from .headers import headers, headers_squads, get_sec_ch_ua
from bot.core.image_checker import get_cords_and_color, template_to_join, inform
from bot.utils.firstrun import append_line_to_file

API_SQUADS_ENDPOINT = "https://api.notcoin.tg"
API_GAME_ENDPOINT = "https://notpx.app/api/v1"


class Tapper:
    def __init__(self, tg_client: TelegramClient):
        self.tg_client = tg_client
        self.session_name, _ = os.path.splitext(os.path.basename(tg_client.session.filename))
        self.lock = AsyncInterProcessLock(
            os.path.join(os.path.dirname(CONFIG_PATH), 'lock_files', f"{self.session_name}.lock"))
        self.headers = headers

        session_config = config_utils.get_session_config(self.session_name, CONFIG_PATH)

        if not all(key in session_config for key in ('api', 'user_agent')):
            logger.critical(self.log_message('CHECK accounts_config.json as it might be corrupted'))
            exit(-1)

        user_agent = session_config.get('user_agent')
        self.headers['user-agent'] = user_agent
        self.headers.update(**get_sec_ch_ua(user_agent))

        self.proxy = session_config.get('proxy')
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = proxy_utils.to_telethon_proxy(proxy)
            self.tg_client.set_proxy(proxy_dict)

        self.balance = 0
        self.template_to_join = 0
        self.user_id = 0

        self._webview_data = None

    def log_message(self, message) -> str:
        return f"<ly>{self.session_name}</ly> | {message}"

    async def initialize_webview_data(self, bot_name: str, short_name: str):
        if not (bot_name or short_name):
            raise InvalidSession
        while True:
            try:
                peer = await self.tg_client.get_input_entity(bot_name)
                bot_id = InputUser(user_id=peer.user_id, access_hash=peer.access_hash)
                input_bot_app = InputBotAppShortName(bot_id=bot_id, short_name=short_name)
                self._webview_data = {'peer': peer, 'app': input_bot_app}
                break
            except FloodWaitError as fl:
                logger.warning(self.log_message(f"FloodWait {fl}. Waiting {fl.seconds}s"))
                await asyncio.sleep(fl.seconds + 3)
            except (UnauthorizedError, AuthKeyUnregisteredError):
                raise InvalidSession(f"{self.session_name}: User is unauthorized")
            except (UserDeactivatedError, UserDeactivatedBanError, PhoneNumberBannedError):
                raise InvalidSession(f"{self.session_name}: User is banned")

    async def get_tg_web_data(self, bot_name: str, short_name: str):
        if self.proxy and not self.tg_client._proxy:
            logger.critical(self.log_message('Proxy found, but not passed to TelegramClient'))
            exit(-1)
        async with self.lock:
            try:
                if not self.tg_client.is_connected():
                    await self.tg_client.connect()
                await self.initialize_webview_data(bot_name, short_name)
                await asyncio.sleep(uniform(1, 2))

                ref_id = None
                if bot_name == "notpixel":
                    ref_id = settings.REF_ID if randint(0, 100) <= 85 else "f525256526"
                elif bot_name == "notgames_bot":
                    ref_id = "aWQ9bnVsbA=="

                web_view = await self.tg_client(messages.RequestAppWebViewRequest(
                    **self._webview_data,
                    platform='android',
                    write_allowed=True,
                    start_param=ref_id
                ))

                auth_url = web_view.url
                tg_web_data = unquote(
                    string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))

                start_param = re.findall(r'start_param=([^&]+)', tg_web_data)

                user = re.findall(r'user=([^&]+)', tg_web_data)[0]
                self.user_id = json.loads(user)['id']

                init_data = {
                    'auth_date': re.findall(r'auth_date=([^&]+)', tg_web_data)[0],
                    'chat_instance': re.findall(r'chat_instance=([^&]+)', tg_web_data)[0],
                    'chat_type': re.findall(r'chat_type=([^&]+)', tg_web_data)[0],
                    'hash': re.findall(r'hash=([^&]+)', tg_web_data)[0],
                    'user': quote(user),
                }

                if start_param:
                    init_data['start_param'] = start_param[0]

                ordering = ["user", "chat_instance", "chat_type", "start_param", "auth_date", "hash"]

                auth_token = '&'.join([var for var in ordering if var in init_data])

                for key, value in init_data.items():
                    auth_token = auth_token.replace(f"{key}", f'{key}={value}')

            except InvalidSession:
                raise

            except Exception as error:
                log_error(self.log_message(f"Unknown error during Authorization: {type(error).__name__}"))
                await asyncio.sleep(delay=3)

            finally:
                if self.tg_client.is_connected():
                    await self.tg_client.disconnect()
                    await asyncio.sleep(15)

        return auth_token

    async def check_proxy(self, http_client: CloudflareScraper) -> bool:
        proxy_conn = http_client.connector
        if proxy_conn and not hasattr(proxy_conn, '_proxy_host'):
            logger.info(self.log_message(f"Running Proxy-less"))
            return True
        try:
            response = await http_client.get(url='https://ifconfig.me/ip', timeout=aiohttp.ClientTimeout(15))
            logger.info(self.log_message(f"Proxy IP: {await response.text()}"))
            return True
        except Exception as error:
            proxy_url = f"{proxy_conn._proxy_type}://{proxy_conn._proxy_host}:{proxy_conn._proxy_port}"
            log_error(self.log_message(f"Proxy: {proxy_url} | Error: {type(error).__name__}"))
            return False

    async def join_squad(self, http_client, tg_web_data: str):
        custom_headers = headers_squads.copy()
        custom_headers['User-Agent'] = self.headers['user-agent']
        custom_headers["bypass-tunnel-reminder"] = "x"
        custom_headers["TE"] = "trailers"
        custom_headers['x-auth-token'] = "Bearer null"
        bearer_token = None
        try:

            if tg_web_data is None:
                logger.error(self.log_message(f"Invalid web_data, cannot join squad"))
            import json
            pl = {"webAppData": tg_web_data}
            login_req = await http_client.post(f"{API_SQUADS_ENDPOINT}/auth/login", json=pl, headers=custom_headers)

            login_req.raise_for_status()

            login_data = await login_req.json()

            bearer_token = login_data.get("data", {}).get("accessToken", None)
            if not bearer_token:
                raise Exception
            logger.success(self.log_message(f"Logged in to NotGames"))
        except Exception as error:
            log_error(self.log_message(f"Unknown error when logging in to NotGames: {error}"))

        custom_headers["x-auth-token"] = f"Bearer {bearer_token}"

        try:
            logger.info(self.log_message("Joining squad.."))
            join_req = await http_client.post(f"{API_SQUADS_ENDPOINT}/squads/absolateA/join",
                                              json={"chatId": -1002312810276}, headers=custom_headers)

            join_req.raise_for_status()
            logger.success(self.log_message(f"Joined squad"))
        except Exception as error:
            log_error(self.log_message(f"Unknown error when joining squad: {error}"))

    async def login(self, http_client: CloudflareScraper):
        try:

            response = await http_client.get(f"{API_GAME_ENDPOINT}/users/me")
            response.raise_for_status()
            response_json = await response.json()
            return response_json

        except Exception as error:
            log_error(self.log_message(f"Unknown error when logging: {error}"))
            await asyncio.sleep(delay=uniform(3, 7))
            await self.login(http_client)

    async def join_and_mute_tg_channel(self, link: str):
        path = link.replace("https://t.me/", "")
        if path == 'money':
            return

        async with self.lock:
            async with self.tg_client as client:
                try:
                    if path.startswith('+'):
                        invite_hash = path[1:]
                        result = await client(messages.ImportChatInviteRequest(hash=invite_hash))
                        channel_title = result.chats[0].title
                        entity = result.chats[0]
                    else:
                        entity = await client.get_entity(f'@{path}')
                        await client(channels.JoinChannelRequest(channel=entity))
                        channel_title = entity.title

                    await asyncio.sleep(1)

                    await client(account.UpdateNotifySettingsRequest(
                        peer=InputNotifyPeer(entity),
                        settings=InputPeerNotifySettings(
                            show_previews=False,
                            silent=True,
                            mute_until=datetime.today() + timedelta(days=365)
                        )
                    ))

                    logger.info(self.log_message(f"Subscribed to channel: <y>{channel_title}</y>"))
                except Exception as e:
                    log_error(self.log_message(f"(Task) Error while subscribing to tg channel: {e}"))

            await asyncio.sleep(15)

    async def get_balance(self, http_client: CloudflareScraper):
        try:
            balance_req = await http_client.get(f'{API_GAME_ENDPOINT}/mining/status')
            balance_req.raise_for_status()
            balance_json = await balance_req.json()
            return balance_json['userBalance']
        except Exception as error:
            log_error(self.log_message(f"Unknown error when processing balance: {error}"))
            await asyncio.sleep(delay=3)

    async def tasks(self, http_client: CloudflareScraper):
        try:
            stats = await http_client.get(f'{API_GAME_ENDPOINT}/mining/status')
            stats.raise_for_status()
            stats_json = await stats.json()
            done_task_list = stats_json['tasks'].keys()
            # logger.debug(done_task_list)
            if randint(0, 5) == 3:
                league_statuses = {"bronze": [], "silver": ["leagueBonusSilver"],
                                   "gold": ["leagueBonusSilver", "leagueBonusGold"],
                                   "platinum": ["leagueBonusSilver", "leagueBonusGold", "leagueBonusPlatinum"]}
                possible_upgrades = league_statuses.get(stats_json["league"], "Unknown")
                if possible_upgrades == "Unknown":
                    logger.warning(self.log_message(
                        f"Unknown league: {stats_json['league']}, contact support with this issue. "
                        f"Provide this log to make league known."))
                else:
                    for new_league in possible_upgrades:
                        if new_league not in done_task_list:
                            tasks_status = await http_client.get(f'{API_GAME_ENDPOINT}/mining/task/check/{new_league}')
                            tasks_status.raise_for_status()
                            tasks_status_json = await tasks_status.json()
                            status = tasks_status_json[new_league]
                            if status:
                                logger.success(self.log_message(
                                    f"League requirement met. Upgraded to {new_league}."))
                                current_balance = await self.get_balance(http_client)
                                logger.info(self.log_message(f"Current balance: {current_balance}"))
                            else:
                                logger.warning(self.log_message(f"League requirements not met."))
                            await asyncio.sleep(delay=uniform(10, 20))
                            break

            for task in settings.TASKS_TO_DO:
                if task not in done_task_list:
                    if task == 'paint20pixels':
                        repaints_total = stats_json['repaintsTotal']
                        if repaints_total < 20:
                            continue
                    if ":" in task:
                        entity, name = task.split(':')
                        task = f"{entity}?name={name}"
                        if entity == 'channel':
                            if not settings.JOIN_TG_CHANNELS:
                                continue
                            await self.join_and_mute_tg_channel(name)
                            await asyncio.sleep(delay=3)
                    tasks_status = await http_client.get(f'{API_GAME_ENDPOINT}/mining/task/check/{task}')
                    tasks_status.raise_for_status()
                    tasks_status_json = await tasks_status.json()
                    status = (lambda r: all(r.values()))(tasks_status_json)
                    if status:
                        logger.success(self.log_message(f"Task requirements met. Task {task} completed"))
                        current_balance = await self.get_balance(http_client)
                        logger.info(self.log_message(f"Current balance: <e>{current_balance}</e>"))
                    else:
                        logger.warning(self.log_message(f"Task requirements were not met {task}"))
                    if randint(0, 1):
                        break
                    await asyncio.sleep(delay=uniform(10, 20))

        except Exception as error:
            log_error(self.log_message(f"Unknown error when processing tasks: {error}"))

    async def make_paint_request(self, http_client: CloudflareScraper, yx, color, delay_start, delay_end):
        paint_request = await http_client.post(f'{API_GAME_ENDPOINT}/repaint/start',
                                               json={"pixelId": int(yx), "newColor": color})
        paint_request.raise_for_status()
        paint_request_json = await paint_request.json()
        cur_balance = paint_request_json.get("balance", self.balance)
        change = max(0, cur_balance - self.balance)
        self.balance = cur_balance
        logger.success(self.log_message(f"Painted {yx} with color: {color} | got <e>{change}</e> points"))
        await asyncio.sleep(delay=randint(delay_start, delay_end))

    async def paint(self, http_client: CloudflareScraper, retries=20):
        try:
            stats = await http_client.get(f'{API_GAME_ENDPOINT}/mining/status')
            stats.raise_for_status()
            stats_json = await stats.json()
            charges = stats_json.get('charges', 24)
            self.balance = stats_json.get('userBalance', 0)
            max_charges = stats_json.get('maxCharges', 24)
            logger.info(self.log_message(f"Charges: <e>{charges}/{max_charges}</e>"))
            if await self.notpx_template(http_client=http_client):
                for _ in range(charges):
                    try:
                        q = await get_cords_and_color(user_id=self.user_id, template=self.template_to_join)
                    except Exception:
                        logger.success(self.log_message(f"No pixels to paint"))
                        return
                    coords = q["coords"]
                    color3x = q["color"]
                    yx = coords
                    await self.make_paint_request(http_client, yx, color3x, 5, 10)
            else:
                for _ in range(charges):
                    x, y = randint(100, 900), randint(100, 900)
                    yx = f'{int(f"{y}{x}") + 1}'
                    await self.make_paint_request(http_client, yx, "#000000", 5, 10)

        except Exception as error:
            log_error(self.log_message(f"Unknown error when painting: {error}"))
            await asyncio.sleep(delay=10)
            if retries > 0:
                await self.paint(http_client=http_client, retries=retries - 1)

    async def upgrade(self, http_client: CloudflareScraper):
        try:
            status_req = await http_client.get(f'{API_GAME_ENDPOINT}/mining/status')
            status_req.raise_for_status()
            status = await status_req.json()
            boosts = status['boosts']
            boosts_max_levels = {
                "energyLimit": settings.ENERGY_LIMIT_MAX_LEVEL,
                "paintReward": settings.PAINT_REWARD_MAX_LEVEL,
                "reChargeSpeed": settings.RECHARGE_SPEED_MAX_LEVEL,
            }
            for name, level in sorted(boosts.items(), key=lambda item: item[1]):
                while name not in settings.IGNORED_BOOSTS and level < boosts_max_levels[name]:
                    try:
                        upgrade_req = await http_client.get(f'{API_GAME_ENDPOINT}/mining/boost/check/{name}')
                        upgrade_req.raise_for_status()
                        logger.success(self.log_message(f"Upgraded boost: {name}"))
                        level += 1
                        await asyncio.sleep(delay=randint(2, 5))
                    except Exception as error:
                        logger.warning(self.log_message(f"Not enough money to keep upgrading."))
                        await asyncio.sleep(delay=uniform(5, 10))
                        return
        except Exception as error:
            log_error(self.log_message(f"Unknown error when upgrading: {error}"))
            await asyncio.sleep(delay=3)

    async def claim(self, http_client: CloudflareScraper):
        try:
            logger.info(self.log_message(f"Claiming mine"))
            response = await http_client.get(f'{API_GAME_ENDPOINT}/mining/status')
            response.raise_for_status()
            response_json = await response.json()
            await asyncio.sleep(delay=5)
            for _ in range(2):
                try:
                    response = await http_client.get(f'{API_GAME_ENDPOINT}/mining/claim')
                    response.raise_for_status()
                    response_json = await response.json()
                except Exception as error:
                    logger.info(self.log_message(f"First claiming not always successful, retrying.."))
                    await asyncio.sleep(delay=randint(20, 30))
                else:
                    break

            return response_json['claimed']
        except Exception as error:
            log_error(self.log_message(f"Unknown error when claiming reward: {error}"))
            await asyncio.sleep(delay=3)

    async def in_squad(self, http_client: CloudflareScraper):
        try:
            logger.info(self.log_message(f"Checking if you're in squad"))
            stats_req = await http_client.get(f'{API_GAME_ENDPOINT}/mining/status')
            stats_req.raise_for_status()
            stats_json = await stats_req.json()
            league = stats_json["league"]
            squads_req = await http_client.get(f'{API_GAME_ENDPOINT}/ratings/squads?league={league}')
            squads_req.raise_for_status()
            squads_json = await squads_req.json()
            squad_id = squads_json.get("mySquad", {"id": None}).get("id", None)
            return True if squad_id else False
        except Exception as error:
            log_error(self.log_message(f"Unknown error when checking squad reward: {error}"))
            await asyncio.sleep(delay=3)
            return True

    async def notpx_template(self, http_client: CloudflareScraper):
        try:
            stats_req = await http_client.get(f'{API_GAME_ENDPOINT}/image/template/my')
            stats_req.raise_for_status()
            cur_template = await stats_req.json()
            return cur_template.get("id")
        except Exception as error:
            return 0

    async def need_join_template(self, http_client: CloudflareScraper):
        try:
            tmpl = await self.notpx_template(http_client)
            self.template_to_join = await template_to_join(tmpl)
            return str(tmpl) != self.template_to_join
        except Exception as error:
            pass
        return False

    async def join_template(self, http_client: CloudflareScraper, template_id):
        try:
            resp = await http_client.put(f"{API_GAME_ENDPOINT}/image/template/subscribe/{template_id}")
            resp.raise_for_status()
            await asyncio.sleep(uniform(1, 3))
            return resp.status == 204
        except Exception as error:
            log_error(self.log_message(f"Unknown error upon joining a template: {error}"))
            return False

    @staticmethod
    def generate_random_string(length=8):
        characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        random_string = ''
        for _ in range(length):
            random_index = int((len(characters) * int.from_bytes(os.urandom(1), 'big')) / 256)
            random_string += characters[random_index]
        return random_string

    async def run(self) -> None:
        random_delay = uniform(1, settings.RANDOM_SESSION_START_DELAY)
        logger.info(self.log_message(f"Bot will start in <ly>{int(random_delay)}s</ly>"))
        await asyncio.sleep(delay=random_delay)

        access_token_created_time = 0

        proxy_conn = {'connector': ProxyConnector.from_url(self.proxy)} if self.proxy else {}
        async with CloudflareScraper(headers=self.headers, timeout=aiohttp.ClientTimeout(60),
                                     **proxy_conn) as http_client:
            while True:
                if not await self.check_proxy(http_client=http_client):
                    logger.warning(self.log_message('Failed to connect to proxy server. Sleep 5 minutes.'))
                    await asyncio.sleep(300)
                    continue

                token_live_time = randint(600, 850)
                try:
                    if settings.NIGHT_MODE:
                        current_utc_time = datetime.utcnow().time()

                        start_time = dtime(settings.NIGHT_TIME[0], 0)
                        end_time = dtime(settings.NIGHT_TIME[1], 0)

                        next_checking_time = randint(settings.NIGHT_CHECKING[0], settings.NIGHT_CHECKING[1])

                        if start_time <= current_utc_time <= end_time:
                            logger.info(self.log_message(
                                f"Current UTC time is {current_utc_time.replace(microsecond=0)}, so bot is sleeping, "
                                f"next checking in {round(next_checking_time / 3600, 1)} hours"))
                            await asyncio.sleep(next_checking_time)
                            continue

                    if time() - access_token_created_time >= token_live_time:
                        tg_web_data = await self.get_tg_web_data(bot_name="notpixel", short_name="app")
                        if not tg_web_data:
                            logger.warning(self.log_message('Failed to get webview URL'))
                            await asyncio.sleep(300)
                            continue

                        http_client.headers["Authorization"] = f"initData {tg_web_data}"
                        logger.info(self.log_message(f"Started logining in"))
                        user_info = await self.login(http_client=http_client)
                        logger.success(self.log_message(f"Successful login"))
                        access_token_created_time = time()
                        sleep_time = randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])

                    await asyncio.sleep(delay=randint(1, 3))

                    balance = await self.get_balance(http_client)
                    logger.info(self.log_message(f"Balance: <e>{balance}</e>"))

                    await inform(self.user_id, balance)

                    joined = await self.need_join_template(http_client=http_client)
                    if joined:
                        result = await self.join_template(http_client, self.template_to_join)
                        if result:
                            logger.success(self.log_message("Successfully joined template"))
                        while not joined:
                            if not result:
                                result = await self.join_template(http_client, self.template_to_join)
                            joined = await self.need_join_template(http_client=http_client)
                            delay = uniform(5, 10)
                            await asyncio.sleep(delay=delay)

                    if settings.AUTO_DRAW:
                        await self.paint(http_client=http_client)

                    if settings.CLAIM_REWARD:
                        reward_status = await self.claim(http_client=http_client)
                        logger.info(self.log_message(f"Claim reward: <e>{reward_status}</e>"))

                    if settings.SQUAD_ID:
                        if not await self.in_squad(http_client=http_client):
                            tg_web_data = await self.get_tg_web_data(bot_name="notgames_bot", short_name="squads")
                            await self.join_squad(http_client, tg_web_data)
                        else:
                            logger.success(self.log_message("You're already in squad"))

                    if settings.AUTO_TASK:
                        logger.info(self.log_message(f"Auto task started"))
                        await self.tasks(http_client=http_client)
                        logger.info(self.log_message(f"Auto task finished"))

                    if settings.AUTO_UPGRADE:
                        reward_status = await self.upgrade(http_client=http_client)

                    logger.info(self.log_message(f"Sleep <y>{round(sleep_time / 60, 1)}</y> min"))
                    await asyncio.sleep(delay=sleep_time)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    log_error(self.log_message(f"Unknown error: {error}"))
                    await asyncio.sleep(delay=uniform(60, 120))


async def run_tapper(tg_client: TelegramClient):
    runner = Tapper(tg_client=tg_client)
    try:
        await runner.run()
    except InvalidSession as e:
        logger.error(runner.log_message(f"Invalid Session: {e}"))
