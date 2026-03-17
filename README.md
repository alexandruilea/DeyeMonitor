# Deye Inverter EMS Pro

A professional Energy Management System for Deye inverters with Tapo smart plug integration for heat pump control.

<!-- README last updated at commit: 634f7d7 (2026-03-16) -->

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
  - Solar-curve-weighted algorithm (cos² from noon) for midday-heavy charging
  - Configurable target SOC, buffer time, and battery capacity
  - 10A step rounding and throttled writes to avoid excessive register writes
  - Automatically coordinates with battery boost protection (protection yields when sunset charging is active)
- 🔥 Automatic heat pump / consumer control based on:
  - Battery SOC thresholds
  - Grid export detection
  - High voltage dumping
- 🔋 **SOC Recovery Hysteresis** - Prevents outlet on/off cycling when SOC is near thresholds:
  - Outlets shut down at Stop SOC are blocked from export/HV restart until SOC recovers to midpoint of (Stop SOC + Start SOC)
  - Prevents heatpump cycling when export limit is reached but battery is low
- ⏱️ **SOC Trigger Delay** - SOC must stay above the start threshold for a configurable duration (default 3 min) before triggering, preventing false starts from transient inverter data read errors
- ⏳ **Export Trigger Delay** - Grid export must sustain above the limit for a configurable duration before triggering, giving battery boost protection time to react first
- 🔄 **Restart Delay** - Configurable cooldown after an outlet turns off before it can auto-restart, preventing rapid on/off cycling
- 🛡️ Safety features:
  - Phase overload protection
  - Critical undervoltage protection
  - Low voltage delay timer with recovery voltage/delay
  - Separate charge/discharge hardware amp limits (multi-battery support)
- 🏛️ **On-Grid Always On** - Optional mode to keep outlets always on when grid is connected
- 📝 **Persistent File Logging** - All console output is duplicated to timestamped log files in a `logs/` directory for post-mortem analysis
- 🎮 Manual override mode
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
    ├── tapo_manager.py     # Tapo smart plug control
    ├── ems_logic.py        # Energy management logic
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

| Variable                            | Description                                  | Default |
| ----------------------------------- | -------------------------------------------- | ------- |
| `PROTECTION_MAX_SELL_POWER`         | Max export power limit (W)                   | 8000    |
| `PROTECTION_POWER_THRESHOLD_PCT`    | Start protection at this % of max export     | 95      |
| `PROTECTION_RECOVERY_THRESHOLD_PCT` | Reduce protection below this %               | 85      |
| `PROTECTION_VOLTAGE_WARNING`        | Start protection above this voltage (V)      | 251.5   |
| `PROTECTION_VOLTAGE_RECOVERY`       | Reduce protection below this voltage (V)     | 249.0   |
| `PROTECTION_CHARGE_STEP`            | Increase charging by this many Amps per step | 10      |
| `PROTECTION_ADJUSTMENT_INTERVAL`    | Seconds between adjustments (stabilization)  | 10      |
| `PROTECTION_ENABLED_AT_STARTUP`     | Enable protection automatically at startup   | true    |
| `PROTECTION_BATTERY_NOMINAL_VOLTAGE`| Nominal battery voltage for proportional calc (V) | 52 |
| `PROTECTION_VOLTAGE_HOLD_MARGIN`    | Hold boost if voltage within this of warning (V) | 5.0 |

#### Sunset Charging Settings

| Variable                  | Description                                          | Default |
| ------------------------- | ---------------------------------------------------- | ------- |
| `SOLAR_LATITUDE`          | Your location latitude                               | 47.00   |
| `SOLAR_LONGITUDE`         | Your location longitude                              | 22.00   |
| `BATTERY_CAPACITY_AH`     | Total battery capacity in Amp-hours                  | 600     |
| `SUNSET_TARGET_SOC`       | Target SOC to reach by sunset (%)                    | 100     |
| `SUNSET_BUFFER_MINUTES`   | Finish charging this many minutes before sunset      | 60      |
| `SUNSET_MIN_CHARGE_AMPS`  | Minimum charge rate when sunset charging is active   | 10      |
| `SUNSET_CHARGING_ENABLED` | Enable sunset-aware charging at startup (true/false) | true    |

#### Tapo Smart Plug Outlets

| Variable            | Description                |
| ------------------- | -------------------------- |
| `OUTLET_N_IP`       | Tapo smart plug IP address |
| `OUTLET_N_USER`     | Tapo account email         |
| `OUTLET_N_PASS`     | Tapo account password      |
| `OUTLET_N_NAME`     | Display name in UI         |
| `OUTLET_N_PRIORITY` | Priority (1=highest)       |

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
| SOC Delay          | Seconds SOC must stay above start before trigger | 180s    |
| Export Limit       | Grid export threshold to trigger outlet (W)      | 15000W  |
| Export Delay       | Seconds export must sustain above limit           | 300s    |
| Restart Delay      | Minutes cooldown before auto-restart after off   | 30min   |
| On-Grid Always On  | Keep outlet always on when grid is connected     | false   |

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
