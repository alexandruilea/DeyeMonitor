"""
Manual MG iSmart connectivity check (not a unit test - it talks to SAIC's EU servers).

By default it is read-only: logs in, lists the linked cars and reads SAIC's cached
status for each (including battery %), without waking the car.
--live, --climate and --seat-* wake the car; the car must be locked for commands.

Only one login per account is allowed: running this logs the same account out of
the iSmart phone app.

Reads credentials from .env: MG_USER / MG_PASS, falling back to MG_CAR_1_USER /
MG_CAR_1_PASS. If the user is a phone number instead of an email, also set
MG_PHONE_COUNTRY_CODE (or MG_CAR_1_PHONE_COUNTRY_CODE), e.g. 40.

Usage:
    python tests/test_mg.py                              # read-only, cached status
    python tests/test_mg.py --live                       # + live battery % (wakes the car)
    python tests/test_mg.py --climate 18 --seat-driver 1 # climate on at 18 C, then driver seat heating on
    python tests/test_mg.py --climate off --seat-driver 0
    --seat-passenger 0-3                                 # passenger seat level (0 if omitted)
    --vin 1234                                           # pick a car by the last VIN digits (if the account has several)
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from saic_ismart_client_ng import SaicApi
from saic_ismart_client_ng.api.vehicle.schema import BasicVehicleStatus, VinInfo
from saic_ismart_client_ng.exceptions import SaicApiException
from saic_ismart_client_ng.model import SaicApiConfiguration

# Seconds to let the car apply a command before reading its status back
READBACK_DELAY = 15

# remoteClimateStatus values, as the MQTT gateway names them
CLIMATE_STATES = {0: "off", 1: "blowing only", 2: "on", 5: "front defrost"}


def mask_vin(vin: str | None) -> str:
    if not vin:
        return "?"
    return f"{vin[:3]}{'*' * (len(vin) - 7)}{vin[-4:]}"


def heated_seat_type(car: VinInfo) -> str:
    """SAIC's HeatedSeat model item: "1" = levels 0-3, "2" = on/off, anything else = not advertised."""
    value = next((c.itemValue for c in car.vehicleModelConfiguration if c.itemCode == "HeatedSeat"), None)
    return {"1": "levels 0-3", "2": "on/off"}.get(value, f"not advertised ({value})")


def climate_temperature_idx(series: str, celsius: int) -> int:
    """SAIC's climate temperature index, as the MQTT gateway computes it (MG4 = EH32 has a different offset)."""
    if series.upper().startswith("EH32"):
        return 3 + celsius - 17
    return 2 + celsius - 16


def climate_arg(value: str) -> str | int:
    if value.lower() == "off":
        return "off"
    celsius = int(value)
    if not 16 <= celsius <= 31:
        raise argparse.ArgumentTypeError("climate temperature must be 16-31 C, or 'off'")
    return celsius


def print_live_status(status: BasicVehicleStatus | None) -> None:
    if not status:
        print("    status: not reported")
        return
    climate = CLIMATE_STATES.get(status.remoteClimateStatus, f"unknown ({status.remoteClimateStatus})")
    print(f"    climate: {climate}, cabin temp: {status.interiorTemperature}, locked: {status.lockStatus}, "
          f"seat heat L/R: {status.frontLeftSeatHeatLevel}/{status.frontRightSeatHeatLevel}")


async def check_connection(username: str, password: str, phone_country_code: str | None,
                           args: argparse.Namespace) -> None:
    config = SaicApiConfiguration.mg_eu(
        username,
        password,
        username_is_email=phone_country_code is None,
        phone_country_code=phone_country_code,
    )
    api = SaicApi(config)
    seats_requested = args.seat_driver is not None or args.seat_passenger is not None
    try:
        step = "login"
        login = await api.login()
        print(f"Login OK (role: {login.role_name}, token expires {api.token_expiration})")

        step = "vehicle list"
        cars = (await api.vehicle_list()).vinList
        print(f"{len(cars)} car(s) linked to this account")
        for car in cars:
            print(f"\n  {car.brandName} {car.modelName} {car.modelYear} ({car.series}) - VIN {mask_vin(car.vin)}")
            print(f"    shared (subaccount): {car.isSubaccount}, activated: {car.isActivate}, "
                  f"current: {car.isCurrentVehicle}")
            print(f"    heated seats: {heated_seat_type(car)}")

            step = f"cached status of {mask_vin(car.vin)}"
            cached = await api.get_vehicle_status_cached(car.vin)
            basic = cached.basicVehicleStatus
            seen = datetime.fromtimestamp(cached.statusTime) if cached.statusTime else "?"
            print(f"    last seen by SAIC: {seen}")
            if basic:
                # extendedData1 is the plain SOC % on EVs (the gateway's fallback source)
                print(f"    battery (cached): {basic.extendedData1}%, outside temp: {basic.exteriorTemperature}, "
                      f"12V battery: {basic.batteryVoltage}, "
                      f"seat heat L/R: {basic.frontLeftSeatHeatLevel}/{basic.frontRightSeatHeatLevel}")

        if not (args.live or args.climate is not None or seats_requested):
            return

        targets = [c for c in cars if c.vin and (not args.vin or c.vin.endswith(args.vin))]
        if len(targets) != 1:
            print(f"\n{len(targets)} car(s) match - use --vin <last digits> to pick exactly one")
            sys.exit(1)
        car = targets[0]
        vin = car.vin
        print(f"\nTarget: {car.modelName} {mask_vin(vin)} (waking the car, this can take a minute)")

        step = "live battery data"
        mgmt = (await api.get_vehicle_charging_management_data(vin)).chrgMgmtData
        if mgmt and mgmt.bmsPackSOCDsp is not None:
            print(f"    battery (live): {mgmt.bmsPackSOCDsp / 10.0}%")
        else:
            print("    battery (live): not reported")

        if args.climate == "off":
            step = "climate -> off"
            await api.stop_ac(vin)
            print("    climate off command accepted")
        elif args.climate is not None:
            step = f"climate -> {args.climate} C"
            idx = climate_temperature_idx(car.series or "", args.climate)
            resp = await api.start_ac(vin, temperature_idx=idx)
            print(f"    climate on command accepted ({args.climate} C, index {idx})")
            print_live_status(resp.basicVehicleStatus)

            # Give the climate time to start before sending the seats, so the seats see it running
            print(f"    waiting {READBACK_DELAY}s, then reading the climate state back...")
            await asyncio.sleep(READBACK_DELAY)
            step = "climate read-back"
            print_live_status((await api.get_vehicle_status(vin)).basicVehicleStatus)

        if seats_requested:
            # Left = driver on left-hand-drive (European) cars
            driver = args.seat_driver or 0
            passenger = args.seat_passenger or 0
            step = f"heated seats -> driver {driver}, passenger {passenger}"
            resp = await api.control_heated_seats(vin, left_side_level=driver, right_side_level=passenger)
            print(f"    heated seats command accepted (driver {driver}, passenger {passenger})")
            print_live_status(resp.basicVehicleStatus)

            print(f"    waiting {READBACK_DELAY}s, then reading the seat levels back...")
            await asyncio.sleep(READBACK_DELAY)
            step = "seat read-back"
            print_live_status((await api.get_vehicle_status(vin)).basicVehicleStatus)
    except SaicApiException as e:
        print(f"\nFAILED at {step}: {e}")
        if "1100003" in str(e):
            print("SAIC says this account's access to the car was revoked. "
                  "Try the owner account, or remove and re-send the share from the owner's app.")
        sys.exit(1)
    finally:
        await api.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual MG iSmart connectivity check")
    parser.add_argument("--live", action="store_true", help="read live battery data (wakes the car)")
    parser.add_argument("--climate", type=climate_arg, metavar="16-31|off",
                        help="start the climate at this temperature in C, or stop it (wakes the car)")
    parser.add_argument("--seat-driver", type=int, choices=range(0, 4), metavar="0-3",
                        help="driver seat heating level (wakes the car)")
    parser.add_argument("--seat-passenger", type=int, choices=range(0, 4), metavar="0-3",
                        help="passenger seat heating level (wakes the car)")
    parser.add_argument("--vin", help="last digits of the VIN to target, if the account has several cars")
    args = parser.parse_args()

    load_dotenv()
    username = os.getenv("MG_USER") or os.getenv("MG_CAR_1_USER")
    password = os.getenv("MG_PASS") or os.getenv("MG_CAR_1_PASS")
    phone_country_code = os.getenv("MG_PHONE_COUNTRY_CODE") or os.getenv("MG_CAR_1_PHONE_COUNTRY_CODE") or None
    if not (username and password):
        sys.exit("Set MG_USER/MG_PASS or MG_CAR_1_USER/MG_CAR_1_PASS (and the phone country code "
                 "if the user is a phone number) in .env")
    asyncio.run(check_connection(username, password, phone_country_code, args))


if __name__ == "__main__":
    main()
