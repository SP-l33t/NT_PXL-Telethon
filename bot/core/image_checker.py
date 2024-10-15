import json

import random
import aiohttp
import asyncio
from PIL import Image
from io import BytesIO

from bot.utils import logger

async def reacheble(times_to_fall=10):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://16.16.232.163/is_reacheble/", ssl=False) as response:
                if response.status == 200:
                    logger.success(f"Connected to server.")
                response.raise_for_status()
    except Exception as e:
        logger.error(f"Server unreachable, retrying in 30 seconds, attempt {10 - times_to_fall + 1}/10")
        await asyncio.sleep(30)
        if times_to_fall > 0:
            return await reacheble(times_to_fall-1)
        exit()

async def participate(username, times_to_fall=10):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(f"https://16.16.232.163/owner_info/",
                                   json={"telegram_tag": username}, ssl=False) as response:
                if response.status == 200:
                    logger.success(f"We will write you on @{username} if you win")
                response.raise_for_status()
    except Exception as e:
        logger.error(f"Server unreachable, retrying in 30 seconds, attempt {10 - times_to_fall + 1}/10")
        await asyncio.sleep(30)
        if times_to_fall > 0:
            return await participate(username, times_to_fall-1)
        exit()

async def inform(user_id, balance, times_to_fall=10):
    try:
        async with aiohttp.ClientSession() as session:
            if not balance:
                balance = 0
            async with session.put(f"https://16.16.232.163/info/", json={
                "user_id": user_id,
                "balance": balance,
            }, ssl=False) as response:
                if response.status == 200:
                    return await response.json()
                response.raise_for_status()
    except Exception as e:
        logger.error(f"Server unreachable, retrying in 30 seconds, attempt {10 - times_to_fall + 1}/10")
        await asyncio.sleep(30)
        if times_to_fall > 0:
            return await inform(user_id, balance, times_to_fall-1)
        exit()

async def get_cords_and_color(user_id, template, times_to_fall=10):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://16.16.232.163/get_pixel/?user_id={user_id}&template={template}", ssl=False) as response:
                if response.status == 200:
                    return await response.json()
                response.raise_for_status()
    except Exception as e:
        logger.error(f"Server unreachable, retrying in 30 seconds, attempt {10 - times_to_fall + 1}/10")
        await asyncio.sleep(30)
        if times_to_fall > 0:
            return await get_cords_and_color(user_id, times_to_fall-1)
        exit()


async def template_to_join(cur_template=0, times_to_fall=10):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://16.16.232.163/get_uncolored/?template={cur_template}", ssl=False) as response:
                if response.status == 200:
                    resp = await response.json()
                    return resp['template']
                response.raise_for_status()
    except Exception as e:
        logger.error(f"Server unreachable, retrying in 30 seconds, attempt {10 - times_to_fall + 1}/10")
        await asyncio.sleep(30)
        if times_to_fall > 0:
            return await get_cords_and_color(cur_template, times_to_fall-1)
        exit()