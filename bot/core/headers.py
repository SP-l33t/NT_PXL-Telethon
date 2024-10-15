import re


headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru,en;q=0.9,en-GB;q=0.8,en-US;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Origin': 'https://app.notpx.app',
    'Referer': 'https://app.notpx.app/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'Sec-Ch-Ua-mobile': '?0',
    'Sec-Ch-Ua-platform': '"Android"',
}

headers_squads = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://webapp.notcoin.tg/",
    "Origin": "https://webapp.notcoin.tg",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    'Sec-Ch-Ua-mobile': '?0',
    'Sec-Ch-Ua-platform': '"Android"',
    "Priority": "u=4",
}


def get_sec_ch_ua(user_agent):
    pattern = r'(Chrome|Chromium)\/(\d+)\.(\d+)\.(\d+)\.(\d+)'

    match = re.search(pattern, user_agent)

    if match:
        browser = match.group(1)
        version = match.group(2)

        if browser == 'Chrome':
            sec_ch_ua = f'"Chromium";v="{version}", "Not;A=Brand";v="24", "Google Chrome";v="{version}"'
        else:
            sec_ch_ua = f'"Chromium";v="{version}", "Not;A=Brand";v="24"'

        return {'sec-ch-ua': sec_ch_ua}
    else:
        return {}
