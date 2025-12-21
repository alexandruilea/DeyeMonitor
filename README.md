# Deye Inverter EMS Pro

A professional Energy Management System for Deye inverters with Tapo smart plug integration for heat pump control.

## Features

- 📊 Real-time monitoring of solar, battery, and grid power
- ⚡ Three-phase voltage and load monitoring
- 🔥 Automatic heat pump control based on:
  - Battery SOC thresholds
  - Grid export detection
  - High voltage dumping
- 🛡️ Safety features:
  - Phase overload protection
  - Critical undervoltage protection
  - Low voltage delay timer
- 🎛️ Manual override mode
- 🔧 Fully configurable parameters

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

## Configuration

### Environment Variables (.env)

| Variable             | Description                 |
| -------------------- | --------------------------- |
| `DEYE_IP`            | Deye inverter IP address    |
| `DEYE_LOGGER_SERIAL` | Deye logger serial number   |
| `DEYE_PORT`          | Modbus port (default: 8899) |
| `TAPO_IP`            | Tapo smart plug IP address  |
| `TAPO_USER`          | Tapo account email          |
| `TAPO_PASS`          | Tapo account password       |

### EMS Parameters (in-app configurable)

| Parameter   | Description                                  | Default |
| ----------- | -------------------------------------------- | ------- |
| Start SOC   | Battery % to start heat pump                 | 70%     |
| Stop SOC    | Battery % to stop heat pump                  | 32%     |
| Headroom    | Required watts available on each phase       | 4000W   |
| Phase Max   | Maximum watts per phase before safety cutoff | 7000W   |
| High V      | Voltage threshold to trigger HV dump         | 252V    |
| Low V       | Voltage threshold to turn off                | 210V    |
| LV Delay    | Seconds to wait before LV shutoff            | 10s     |
| Critical LV | Safety voltage cutoff (immediate)            | 185V    |

## Usage

Run the application:

```bash
python main.py
```

## Building Standalone Executable

You can build a standalone executable that doesn't require Python to be installed.

### Prerequisites

```bash
pip install pyinstaller
```

### Windows Build

```bash
pyinstaller build.spec --clean
```

The executable will be created at `dist/DeyeEMS.exe` (~18 MB).

#### Running on Windows

1. Copy `DeyeEMS.exe` from the `dist/` folder to your desired location
2. Copy your `.env` file to the **same folder** as the executable
3. Double-click `DeyeEMS.exe` to run

### Linux Build

> **Note:** You must build on Linux to create a Linux executable. PyInstaller does not support cross-compilation.

1. Install system dependencies (Ubuntu/Debian):

   ```bash
   sudo apt-get update
   sudo apt-get install python3-tk python3-venv
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

4. Build the executable:
   ```bash
   pyinstaller build.spec --clean
   ```

The executable will be created at `dist/DeyeEMS` (~20-25 MB).

#### Running on Linux

1. Copy `DeyeEMS` from the `dist/` folder to your desired location
2. Copy your `.env` file to the **same folder** as the executable
3. Make it executable (if not already):
   ```bash
   chmod +x DeyeEMS
   ```
4. Run the application:
   ```bash
   ./DeyeEMS
   ```

> **Note:** The `.env` file must be in the same directory as the executable for configuration to work.

## License

MIT License
