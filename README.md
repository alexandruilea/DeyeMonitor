# Deye Inverter EMS Pro

A professional Energy Management System for Deye inverters with Tapo smart plug integration for heat pump control.

## Features

- 📊 Real-time monitoring of solar, battery, and grid power
- ⚡ Three-phase voltage and load monitoring
- � **Charge Schedule Control** - Time-based automatic charge current adjustment
- 🛡️ **Battery Boost Protection** - Automatically increases battery charging to absorb excess power when:
  - Export power approaches max sell limit
  - Phase voltage exceeds warning threshold
- 🔥 Automatic heat pump control based on:
  - Battery SOC thresholds
  - Grid export detection
  - High voltage dumping
- 🛡️ Safety features:
  - Phase overload protection
  - Critical undervoltage protection
  - Low voltage delay timer
- 🎛️ Manual override mode
- 🔧 Fully configurable parameters via `.env` file

## Project Structure

```
├── .env                    # Hardware configuration (create from .env.example)
├── .env.example            # Example configuration template
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
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

| Variable                     | Description                              | Default |
| ---------------------------- | ---------------------------------------- | ------- |
| `DEYE_MAX_UPS_TOTAL_POWER`   | Maximum UPS output across all phases (W) | 16000   |
| `DEYE_PHASE_MAX`             | Maximum safe power per phase (W)         | 7000    |
| `DEYE_SAFETY_LV`             | Critical low voltage threshold (V)       | 185.0   |
| `DEYE_MAX_CHARGE_AMPS_LIMIT` | Hardware max charging current (A)        | 185     |

#### Inverter Register Addresses (Model-Specific)

| Variable                        | Description                      | Default |
| ------------------------------- | -------------------------------- | ------- |
| `DEYE_REG_MAX_CHARGE_AMPS`      | Max charging current register    | 108     |
| `DEYE_REG_MAX_DISCHARGE_AMPS`   | Max discharging current register | 109     |
| `DEYE_REG_GRID_CHARGE_CURRENT`  | Grid charge current register     | 128     |
| `DEYE_REG_MAX_SOLAR_SELL_POWER` | Max solar sell power register    | 340     |

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

| Parameter         | Description                                  | Default |
| ----------------- | -------------------------------------------- | ------- |
| Start SOC         | Battery % to start outlet                    | 70%     |
| Stop SOC          | Battery % to stop outlet                     | 32%     |
| Headroom          | Required watts available on target phase     | 4000W   |
| Phase Max         | Maximum watts per phase before safety cutoff | 7000W   |
| High V            | Voltage threshold to trigger HV dump         | 252V    |
| Low V             | Voltage threshold to turn off                | 210V    |
| LV Delay          | Seconds to wait before LV shutoff            | 10s     |
| LV Recovery V     | Voltage required for recovery                | 220V    |
| LV Recovery Delay | Seconds voltage must stay above recovery     | 300s    |
| Critical LV       | Safety voltage cutoff (immediate)            | 185V    |

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

> **Note:** You must build on Linux to create a Linux executable. PyInstaller does not support cross-compilation.

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
