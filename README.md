# Deye Inverter EMS Pro

A professional Energy Management System for Deye inverters with Tapo smart plug and Tuya socket thermostat integration for heat pump and consumer load control.

<!-- README last updated at commit: abc73e3 (2026-03-26) -->

## Features

- 📊 Real-time monitoring of solar, battery, and grid power
- ⚡ Three-phase voltage and load monitoring
- 🕐 **Charge Schedule Control** - Time-based automatic charge current adjustment with configurable default schedules in `.env`
- 💰 **Battery Selling Mode** - Sell battery power during peak tariff windows:
  - Switches to "Selling First" work mode during sell windows with configurable sell power
  - Automatically restores Zero Export mode when sell window ends
  - ⚠️ CT clamp readings are ignored during sell windows (see `.env` documentation)
- 🛡️ **Battery Boost Protection** - Automatically increases battery charging to absorb excess power when:
  - Export power approaches max sell limit
  - Phase voltage exceeds warning threshold
  - Proportional response: large deviations get proportional amp jumps, small ones use fine-tuning steps
  - Voltage hold margin prevents premature recovery while voltage is still elevated
  - Persists boost level across app restarts (reads current inverter state on startup)
  - Register write throttling to reduce inverter flash/EEPROM wear
  - Verifies inverter has caught up to current charge setting before adjusting further
- 🌅 **Sunset-Aware Charging** - Dynamically adjusts charge rate throughout the day to reach target SOC by sunset:
  - Offline astronomical calculations via `astral` library (no internet needed)
  - Solar-curve-weighted algorithm (cos²) for production-peak-heavy charging
  - Configurable peak solar hour for non-south-facing panels (or auto = solar noon)
  - Cloudy day compensation: compares 15-min rolling PV average against expected cos² curve; boosts charging when production drops below threshold
  - Configurable target SOC, buffer time, and battery capacity
  - 10A step rounding and throttled writes to avoid excessive register writes
  - Automatically coordinates with battery boost protection (protection yields when sunset charging is active)
- 🔥 **Heat Pump – Socket Thermostat (Tuya)** - Intelligent heat pump control via a Tuya socket thermostat (e.g. "Priză termostat PDC"):
  - _Control_: Sets target temperature and hysteresis on the device; the thermostat firmware handles relay switching instantly (no relay toggling from the app)
  - _Scheduling_: Time-based intervals with min/max temperature ranges; device turns ON below min, OFF at max
  - _Overrides_ (evaluated in priority order):
    - **LV shutdown** — Forces OFF after sustained low voltage; recovery requires voltage above threshold for a configurable delay
    - **HV dump** — Forces ON (80 °C) when any phase exceeds HV threshold; hysteresis OFF with delay below HV OFF threshold
    - **SOC low** — Forces OFF with configurable delay, then locks out schedule until SOC recovers to ON threshold
    - **SOC high** — Forces ON using the active schedule temperature (not 80 °C) when SOC ≥ ON threshold; deactivates on sustained grid import > 50 % of HP power
    - **Solar export** — Forces ON (80 °C) when grid export exceeds threshold for a sustained delay period; same delay applies before deactivating on grid import, riding through brief inverter glitches
  - _Monitoring_: Supports L1, L2, L3, or ANY phase (uses min voltage for LV, max for HV); live "OFF in Xs" / "Recovery in Xs" countdown for all delayed transitions
- 🔌 **EV Smart Charger (Tuya)** - Intelligent EV charging via a Tuya-enabled charger (e.g. feyree):
  - _Charging modes_:
    - **Fixed-rate** — Charges at max amps while home battery SOC is above start threshold
    - **Solar-follow** — Scales amperage in real time based on solar surplus (PV production minus house consumption); ramps up instantly but ramps down only in significant steps (e.g. 32→24→16→8A) with a configurable delay between steps to avoid frequent charger restarts that can upset the car
    - **Grid charge** — Always charges at configured amps while grid is connected
    - **Battery pacing** — At night, spreads charge over remaining hours until a target time to avoid draining the house battery
  - _Protection_:
    - **SOC-gated** — Only starts when SOC ≥ start threshold; stops if it drops to stop threshold
    - **Grid-pull stop** — Stops charging if grid import is sustained for 5+ minutes (battery exhausted)
    - **Safe amp changes** — Stops charger before lowering amps, waits 5 s, then restarts to prevent overcurrent trips
  - _Rate limiting_: Configurable cooldown between any charger state changes
- 🔥 **Tapo Smart Plug Outlets** - Automatic consumer control via TP-Link Tapo smart plugs:
  - _Triggers_: Battery SOC threshold, grid export detection, high-voltage dumping
  - _Safety_:
    - **SOC recovery hysteresis** — Outlets shut down at Stop SOC are blocked from restart until SOC recovers to midpoint of (Stop SOC + Start SOC)
    - **SOC trigger delay** — SOC must stay above start threshold for a configurable duration (default 3 min) to prevent false starts
    - **Export trigger delay** — Grid export must sustain above the limit before triggering, giving battery boost protection time to react first
    - **Phase overload protection** — Per-phase watt limit with immediate cutoff
    - **Critical undervoltage** — Immediate shutdown at safety voltage
    - **LV delay + recovery** — Low voltage timer with recovery voltage/delay
  - _Modes_:
    - **Restart delay** — Configurable cooldown after off before auto-restart
    - **On-Grid Always On** — Keep outlets always on when grid is connected
    - **Manual override** — Direct on/off control from the UI
- 📝 **Persistent File Logging** - All console output is duplicated to timestamped log files in a `logs/` directory for post-mortem analysis
- 🔧 Fully configurable parameters via `.env` file

## Project Structure

```
├── .env                    # Hardware configuration (create from .env.example)
├── .env.example            # Example configuration template
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
├── build.spec              # PyInstaller spec for Windows build
├── build_linux.spec        # PyInstaller spec for Linux build
├── installer.iss           # Inno Setup script for Windows installer
├── Dockerfile.linux        # Docker cross-compilation for Linux from Windows
├── logs/                   # Timestamped log files (auto-created)
└── src/
    ├── __init__.py         # Package exports
    ├── config.py           # Configuration management
    ├── deye_inverter.py    # Deye inverter communication
    ├── ems_logic.py        # Energy management logic (Tapo outlets)
    ├── ev_logic.py         # EV smart charging decision engine
    ├── tapo_manager.py     # Tapo smart plug control
    ├── tuya_charger.py     # Tuya EV charger device manager
    ├── tuya_heatpump.py    # Tuya thermostat device manager
    ├── tuya_heatpump_logic.py  # Heat pump decision engine
    └── ui_components.py    # CustomTkinter UI widgets
```

## Installation

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   source venv/bin/activate  # Linux/Mac
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and configure your settings:
   ```bash
   copy .env.example .env  # Windows
   cp .env.example .env    # Linux/Mac
   ```
5. Edit `.env` with your inverter and Tapo device details

## Start the app with the venv environment

.venv/Scripts/python.exe main.py

## Configuration

### Environment Variables (.env)

#### Inverter Connection

| Variable             | Description                 |
| -------------------- | --------------------------- |
| `DEYE_IP`            | Deye inverter IP address    |
| `DEYE_LOGGER_SERIAL` | Deye logger serial number   |
| `DEYE_PORT`          | Modbus port (default: 8899) |
| `DEYE_MODEL`         | Inverter model name         |

#### Inverter Power Limits (Model-Specific)

| Variable                        | Description                              | Default |
| ------------------------------- | ---------------------------------------- | ------- |
| `DEYE_MAX_UPS_TOTAL_POWER`      | Maximum UPS output across all phases (W) | 16000   |
| `DEYE_PHASE_MAX`                | Maximum safe power per phase (W)         | 7000    |
| `DEYE_SAFETY_LV`                | Critical low voltage threshold (V)       | 185.0   |
| `DEYE_MAX_CHARGE_AMPS_LIMIT`    | Hardware max charging current (A)        | 185     |
| `DEYE_MAX_DISCHARGE_AMPS_LIMIT` | Hardware max discharging current (A)     | 185     |

#### Inverter Register Addresses (Model-Specific)

| Variable                        | Description                      | Default |
| ------------------------------- | -------------------------------- | ------- |
| `DEYE_REG_MAX_CHARGE_AMPS`      | Max charging current register    | 108     |
| `DEYE_REG_MAX_DISCHARGE_AMPS`   | Max discharging current register | 109     |
| `DEYE_REG_GRID_CHARGE_CURRENT`  | Grid charge current register     | 128     |
| `DEYE_REG_MAX_SOLAR_SELL_POWER` | Max solar sell power register    | 143     |

#### Default Schedule Rows

Schedule rows are pre-loaded into the schedule panel at startup. Format:

```
SCHEDULE_N=HH:MM-HH:MM,max_charge,grid_charge,max_discharge,sell|nosell,sell_power
```

Example:

```env
SCHEDULE_1=23:00-06:00,40,40,185,sell,500
SCHEDULE_2=06:00-09:00,40,40,185,nosell,8000
```

> ⚠️ **Warning:** When `sell=sell`, the inverter switches to "Selling First" work mode which **ignores CT clamp readings**. Any loads that are usually read by the CT clamps (e.g. EV chargers, heat pumps) will NOT be accounted for. The inverter will export up to `sell_power` watts regardless of what those loads are consuming. When the sell window ends, the inverter returns to Zero Export mode and CT clamp readings are restored.

#### Battery Boost Protection Settings

| Variable                             | Description                                       | Default |
| ------------------------------------ | ------------------------------------------------- | ------- |
| `PROTECTION_MAX_SELL_POWER`          | Max export power limit (W)                        | 8000    |
| `PROTECTION_POWER_THRESHOLD_PCT`     | Start protection at this % of max export          | 95      |
| `PROTECTION_RECOVERY_THRESHOLD_PCT`  | Reduce protection below this %                    | 85      |
| `PROTECTION_VOLTAGE_WARNING`         | Start protection above this voltage (V)           | 251.5   |
| `PROTECTION_VOLTAGE_RECOVERY`        | Reduce protection below this voltage (V)          | 249.0   |
| `PROTECTION_CHARGE_STEP`             | Increase charging by this many Amps per step      | 10      |
| `PROTECTION_ADJUSTMENT_INTERVAL`     | Seconds between adjustments (stabilization)       | 10      |
| `PROTECTION_ENABLED_AT_STARTUP`      | Enable protection automatically at startup        | true    |
| `PROTECTION_BATTERY_NOMINAL_VOLTAGE` | Nominal battery voltage for proportional calc (V) | 52      |
| `PROTECTION_VOLTAGE_HOLD_MARGIN`     | Hold boost if voltage within this of warning (V)  | 5.0     |

#### Sunset Charging Settings

| Variable                     | Description                                                           | Default |
| ---------------------------- | --------------------------------------------------------------------- | ------- |
| `SOLAR_LATITUDE`             | Your location latitude                                                | 47.00   |
| `SOLAR_LONGITUDE`            | Your location longitude                                               | 22.00   |
| `BATTERY_CAPACITY_AH`        | Total battery capacity in Amp-hours                                   | 600     |
| `SUNSET_TARGET_SOC`          | Target SOC to reach by sunset (%)                                     | 100     |
| `SUNSET_BUFFER_MINUTES`      | Finish charging this many minutes before sunset                       | 60      |
| `SUNSET_MIN_CHARGE_AMPS`     | Minimum charge rate when sunset charging is active                    | 10      |
| `SUNSET_PEAK_SOLAR_HOUR`     | Peak solar production hour in local time (e.g. 13.5); 0 = auto (noon) | 0       |
| `SUNSET_PEAK_EXPECTED_KW`    | Peak clear-sky PV output in kW (e.g. 14); 0 = no cloudy compensation  | 0       |
| `SUNSET_CLOUD_THRESHOLD_PCT` | Below this % of expected PV → apply cloudy boost                      | 60      |
| `SUNSET_CLOUD_MAX_BOOST`     | Maximum cloudy-day boost multiplier                                   | 3.0     |
| `SUNSET_CHARGING_ENABLED`    | Enable sunset-aware charging at startup (true/false)                  | true    |

#### Tapo Smart Plug Outlets

| Variable            | Description                |
| ------------------- | -------------------------- |
| `OUTLET_N_IP`       | Tapo smart plug IP address |
| `OUTLET_N_USER`     | Tapo account email         |
| `OUTLET_N_PASS`     | Tapo account password      |
| `OUTLET_N_NAME`     | Display name in UI         |
| `OUTLET_N_PRIORITY` | Priority (1=highest)       |

#### TEV Smart Charger (Tuya)

| Variable                           | Descriptio n                                                | Default      |
| ---------------------------------- | ----------------------------------------------------------- | ------------ |
| `EV_CHARGER_ENABLED      `         | Enable EV charger control at startu p                       | `false`      |
| `EV_CHARGER_DEVICE_ID  `           | Tuya Device ID (from `tinytuya wizard` )                    |              |
| `EV_CHARGER_IP     `               | Charger IP address on local networ k                        |              |
| `EV_CHARGER_LOCAL_KEY       `      | Tuya Local Key (from `tinytuya wizard` )                    |              |
| `EV_CHARGER_PROTOCOL_VERSION`      | Tuya protocol version (3.3 / 3.4 )                          | `3.3  `      |
| `EV_CHARGER_MIN_AMPS`              | Minimum charging current (A )                               | `8    `      |
| `EV_CHARGER_MAX_AMPS    `          | Maximum charging current (A )                               | `32   `      |
| `EV_CHARGER_STOP_SOC`              | Stop EV charging when home battery drops below this SOC (%) | `20  `       |
| `EV_CHARGER_START_SOC    `         | Only start EV charging above this SOC (% )                  | `80 `        |
| `EV_CHARGER_SOLAR_MODE`            | Scale amps based on solar export surplu s                   | `false`      |
| `EV_CHARGER_CHANGE_INTERVAL`       | Minutes between charger state change s                      | `5    `      |
| `EV_CHARGER_CHARGE_BY_HOUR  `      | Target hour (0-23) for battery-paced chargin g              | `7    `      |
| `EV_CHARGER_GRID_CHARGE_AMPS`      | Amps to use in grid charge mod e                            | `20   `      |
| `EV_CHARGER_SOLAR_RAMP_DOWN_DELAY` | Minutes between solar ramp-down steps                       | `5`          |
| `EV_CHARGER_SOLAR_AMP_STEPS`       | Comma-separated significant amp levels for ramp-down        | `8,16,24,32` |

**Tuya DPS Mapping (charger model-specific):**

| Variabl e                  | Descriptio n                                           | Default |
| -------------------------- | ------------------------------------------------------ | ------- |
| `EV_CHARGER_DP_SWITCH  `   | DP for on/off switc h                                  | `1  `   |
| `EV_CHARGER_DP_AMPS`       | DP for current settin g                                | `6    ` |
| `EV_CHARGER_DP_STATE     ` | DP for charger state strin g                           | `124  ` |
| `EV_CHARGER_DP_AMPS_SCALE` | Scale factor: `1`=amps, `10`=amps×10, `1000`=milliamps | `1    ` |

#### uya Heat Pump – Socket Thermostat

| Variable                    | Description                              | Default     |
| --------------------------- | ---------------------------------------- | ----------- |
| `HEATPUMP_ENABLED`          | Enable Tuya heat pump control at startup | `false`     |
| `HEATPUMP_DEVICE_ID`        | Tuya Device ID (from `tinytuya wizard`)  |             |
| `HEATPUMP_IP`               | Outlet IP address on local network       |             |
| `HEATPUMP_LOCAL_KEY`        | Tuya Local Key (from `tinytuya wizard`)  |             |
| `HEATPUMP_PROTOCOL_VERSION` | Tuya protocol version (3.3 / 3.4 / 3.5)  | `3.5`       |
| `HEATPUMP_NAME`             | Display name in UI                       | `Heat Pump` |

**Tuya DPS Mapping (device model-specific):**

| Variable                         | Description                                                 | Default |
| -------------------------------- | ----------------------------------------------------------- | ------- |
| `HEATPUMP_DP_SWITCH`             | DP for relay state (read-only in thermostat mode)           | `2`     |
| `HEATPUMP_DP_TEMPERATURE`        | DP for current temperature (scaled)                         | `6`     |
| `HEATPUMP_DP_TEMP_SET`           | DP for target temperature setting                           | `17`    |
| `HEATPUMP_DP_HYSTERESIS`         | DP for hysteresis value                                     | `111`   |
| `HEATPUMP_DP_MODE`               | DP for thermostat mode (heat/cool)                          | `4`     |
| `HEATPUMP_DP_TEMP_SCALE`         | Scale factor: `1`=°C direct, `10`=°C×10                     | `10`    |
| `HEATPUMP_STANDBY_TARGET`        | Target temp when standby (very low = relay OFF)             | `-30`   |
| `HEATPUMP_SOLAR_OVERRIDE_TARGET` | Target temp during solar/HV override (very high = relay ON) | `80`    |

**Solar Override:**

| Variable                             | Description                                                                    | Default |
| ------------------------------------ | ------------------------------------------------------------------------------ | ------- |
| `HEATPUMP_SOLAR_OVERRIDE`            | Enable solar override                                                          | `true`  |
| `HEATPUMP_SOLAR_OVERRIDE_EXPORT_MIN` | Min grid export (W) to trigger ON                                              | `3000`  |
| `HEATPUMP_SOLAR_OVERRIDE_HP_POWER`   | HP rated power (W) — stops if grid import > half                               | `3000`  |
| `HEATPUMP_SOLAR_OVERRIDE_DELAY`      | Seconds export/import must sustain before solar override activates/deactivates | `60`    |

**SOC Overrides:**

| Variable                     | Description                                     | Default |
| ---------------------------- | ----------------------------------------------- | ------- |
| `HEATPUMP_SOC_ON_THRESHOLD`  | SOC ≥ this % → force ON (uses schedule temp)    | `90`    |
| `HEATPUMP_SOC_OFF_THRESHOLD` | SOC ≤ this % → force OFF (with delay + lockout) | `30`    |

**Voltage Overrides:**

| Variable                       | Description                                    | Default |
| ------------------------------ | ---------------------------------------------- | ------- |
| `HEATPUMP_TARGET_PHASE`        | Phase to monitor: L1 / L2 / L3 / ANY           | `ANY`   |
| `HEATPUMP_HV_THRESHOLD`        | High voltage dump ON (V)                       | `252.0` |
| `HEATPUMP_HV_OFF_THRESHOLD`    | HV hysteresis OFF (V)                          | `245.0` |
| `HEATPUMP_LV_THRESHOLD`        | Low voltage shutdown (V)                       | `210.0` |
| `HEATPUMP_LV_RECOVERY_VOLTAGE` | Voltage required for LV recovery (V)           | `220.0` |
| `HEATPUMP_LV_RECOVERY_DELAY`   | Seconds voltage must stay above recovery level | `300`   |
| `HEATPUMP_PHASE_CHANGE_DELAY`  | Seconds before voltage triggers activate       | `10`    |

**Temperature Schedule Slots:**

Format: `HEATPUMP_SCHEDULE_N=HH:MM-HH:MM,min_temp,max_temp`

The thermostat is set to: `target=max_temp`, `hysteresis=(max_temp - min_temp)`. Device firmware handles relay: ON when temp < min_temp, OFF when temp ≥ max_temp.

```env
HEATPUMP_SCHEDULE_1=06:00-16:00,28,35       # Daytime: maintain 28-35°C
HEATPUMP_SCHEDULE_2=16:00-18:00,40,45       # Peak hours: maintain 40-45°C
HEATPUMP_SCHEDULE_3=18:00-06:00,28,35       # Evening/night: maintain 28-35°C
```

### EMS Parameters (in-app configurable)

#### Charge Schedule

| Parameter   | Description                                  | Default |
| ----------- | -------------------------------------------- | ------- |
| Max Charge  | Maximum charging current from any source (A) | 60A     |
| Grid Charge | Maximum charging current from grid (A)       | 40A     |

#### Outlet Control

| Parameter         | Description                                       | Default |
| ----------------- | ------------------------------------------------- | ------- |
| Start SOC         | Battery % to start outlet                         | 70%     |
| Stop SOC          | Battery % to stop outlet                          | 32%     |
| Headroom          | Required watts available on target phase          | 4000W   |
| Phase             | Phase to monitor: L1, L2, L3, or ANY (all phases) | ANY     |
| Phase Max         | Maximum watts per phase before safety cutoff      | 7000W   |
| High V            | Voltage threshold to trigger HV dump              | 252V    |
| Low V             | Voltage threshold to turn off                     | 210V    |
| LV Delay          | Seconds to wait before LV shutoff                 | 10s     |
| LV Recovery V     | Voltage required for recovery                     | 220V    |
| LV Recovery Delay | Seconds voltage must stay above recovery          | 300s    |
| Critical LV       | Safety voltage cutoff (immediate)                 | 185V    |
| SOC Delay         | Seconds SOC must stay above start before trigger  | 180s    |
| Export Limit      | Grid export threshold to trigger outlet (W)       | 15000W  |
| Export Delay      | Seconds export must sustain above limit           | 300s    |
| Restart Delay     | Minutes cooldown before auto-restart after off    | 30min   |
| On-Grid Always On | Keep outlet always on when grid is connected      | false   |

#### EV Smart Charger

| Parameter     | Description                                              | Default    |
| ------------- | -------------------------------------------------------- | ---------- |
| Enable        | Enable/disable EV charger control                        | Off        |
| Min Amps      | Minimum charging current                                 | 8A         |
| Max Amps      | Maximum charging current                                 | 32A        |
| Start SOC     | Home battery SOC to start EV charging                    | 80%        |
| Stop SOC      | Home battery SOC to stop EV charging                     | 20%        |
| Charge by     | Target hour for battery-paced charging (night)           | 7:00       |
| Cooldown      | Minutes between charger state changes                    | 5 min      |
| Solar Follow  | Scale amps to match solar surplus (PV minus house loads) | Off        |
| Grid charge   | Always charge at configured amps while grid is available | Off        |
| Grid charge A | Amps to use in grid charge mode                          | 20A        |
| Ramp ↓ delay  | Minutes between solar ramp-down steps                    | 5 min      |
| Amp steps     | Significant amp levels for ramp-down (comma-separated)   | 8,16,24,32 |

### Heat Pump – Socket Thermostat

| Parameter        | Description                                                                    | Default |
| ---------------- | ------------------------------------------------------------------------------ | ------- |
| Solar Override   | Enable/disable solar export override                                           | On      |
| Trigger W        | Minimum grid export watts to trigger solar override ON                         | 3000W   |
| HP Power W       | Heat pump rated power — solar override stops if grid import > half             | 3000W   |
| Delay s          | Seconds export/import must sustain before solar override activates/deactivates | 60s     |
| SOC ON %         | SOC ≥ this → force ON using schedule temp                                      | 90%     |
| SOC OFF %        | SOC ≤ this → force OFF with delay + lockout                                    | 30%     |
| HV ON V          | Voltage threshold to trigger HV dump (80 °C target)                            | 252V    |
| HV OFF V         | HV hysteresis OFF threshold                                                    | 245V    |
| LV OFF V         | Low voltage shutdown threshold                                                 | 210V    |
| Delay s          | Seconds voltage must sustain before HV/LV triggers                             | 10s     |
| LV Recovery V    | Voltage required for LV recovery                                               | 220V    |
| Recovery Delay s | Seconds voltage must stay above recovery threshold                             | 300s    |
| Schedule slots   | Time intervals with min/max temperature ranges                                 | —       |

## Usage

Run the application:

```bash
python main.py
```

## Building

### Prerequisites

Make sure you have the project virtual environment set up:

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
pip install pyinstaller
```

### Building the Executable

Use the project venv to keep the build small (~16 MB):

```bash
.\venv\Scripts\pyinstaller.exe build.spec --clean    # Windows
./venv/bin/pyinstaller build.spec --clean             # Linux
```

The executable will be created at `dist/DeyeEMS.exe` (Windows) or `dist/DeyeEMS` (Linux).

### Building the Windows Installer

The project includes an [Inno Setup](https://jrsoftware.org/isinfo.php) script to create a proper Windows installer with Start Menu shortcuts and uninstaller.

1. Install [Inno Setup 6](https://jrsoftware.org/isdl.php) (or via `winget install JRSoftware.InnoSetup`)
2. First build the executable (see above)
3. Build the installer:
   ```bash
   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
   ```
   Or open `installer.iss` in Inno Setup and click **Build > Compile**.

The installer will be created at `dist/DeyeEMS_Setup.exe` (~18 MB).

#### What the installer does

- Installs `DeyeEMS.exe` to `Program Files` (or per-user location)
- Creates a `.env` config file from the included template (won't overwrite existing)
- Adds Start Menu shortcuts for the app and for editing the config
- Optional desktop shortcut
- Full uninstaller

### Running on Windows

**From installer:** Run `DeyeEMS_Setup.exe`, follow the wizard, then launch from the Start Menu or desktop shortcut. Edit the `.env` file in the install folder with your inverter settings.

**Portable (no install):** Copy `dist/DeyeEMS.exe` and your `.env` file to any folder, then double-click to run.

### Running on Linux

#### Option 1: Docker Cross-Compilation (from Windows)

Build the Linux executable without a Linux machine:

```bash
docker build -f Dockerfile.linux -t deye-linux-build .
docker run --rm -v ./dist_linux:/dist deye-linux-build
```

The output `dist_linux/DeyeEMS.tar` can be copied to your Linux machine:

```bash
tar xf DeyeEMS.tar
./DeyeEMS
```

#### Option 2: Build Natively on Linux

> **Note:** PyInstaller does not support cross-compilation, so native builds require a Linux environment.

1. Install system dependencies (Ubuntu/Debian):

   ```bash
   sudo apt-get update
   sudo apt-get install python3-tk python3-venv
   ```

2. Build the executable using the venv (see above)

3. Copy `DeyeEMS` from `dist/` to your desired location along with your `.env` file

4. Make it executable and run:
   ```bash
   chmod +x DeyeEMS
   ./DeyeEMS
   ```

> **Note:** The `.env` file must be in the same directory as the executable for configuration to work.

## License

MIT License
