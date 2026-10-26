"""
Manual Tapo connectivity check (not a unit test - it talks to a real plug).

Reads credentials from .env: TAPO_USER / TAPO_PASS / TAPO_IP, falling back to
OUTLET_1_USER / OUTLET_1_PASS / OUTLET_1_IP.

Usage: python tests/test_tapo.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
from tapo import ApiClient


async def check_connection(username: str, password: str, ip: str) -> None:
    # Must be the owner account - shared devices may not work with the API
    client = ApiClient(username, password)
    device = await client.p110(ip)
    info = await device.get_device_info()
    print(f"Connected! Device on: {info.device_on}")


def main() -> None:
    load_dotenv()
    username = os.getenv("TAPO_USER") or os.getenv("OUTLET_1_USER")
    password = os.getenv("TAPO_PASS") or os.getenv("OUTLET_1_PASS")
    ip = os.getenv("TAPO_IP") or os.getenv("OUTLET_1_IP")
    if not (username and password and ip):
        sys.exit("Set TAPO_USER/TAPO_PASS/TAPO_IP (or OUTLET_1_USER/OUTLET_1_PASS/OUTLET_1_IP) in .env")
    asyncio.run(check_connection(username, password, ip))


if __name__ == "__main__":
    main()
