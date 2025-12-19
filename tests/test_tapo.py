import asyncio
import os
from dotenv import load_dotenv
from tapo import ApiClient

load_dotenv()

async def test():
    # Try owner account - shared devices may not work with API
    client = ApiClient("alexandruilea95@gmail.com", "N44Xb0c*0ntIequw8V2D")
    device = await client.p110(os.getenv("TAPO_IP"))
    info = await device.get_device_info()
    print(f"Connected! Device on: {info.device_on}")

asyncio.run(test())
