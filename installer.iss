; Inno Setup Script for Deye Inverter EMS Pro
; Build with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define MyAppName "Deye Inverter EMS Pro"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "DeyeMonitor"
#define MyAppExeName "DeyeEMS.exe"

[Setup]
AppId={{B3F8A1D2-7E4C-4A9B-8D5F-1C6E2A3B4D5E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output installer to dist/ folder
OutputDir=dist
OutputBaseFilename=DeyeEMS_Setup
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Windows version requirement
MinVersion=10.0
; Installer privileges - per-user install by default (no admin needed)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; UI
WizardStyle=modern
SetupIconFile=icon.ico
; Uninstaller
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\DeyeEMS.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Main executable
Source: "dist\DeyeEMS.exe"; DestDir: "{app}"; Flags: ignoreversion
; Example config - only install if user doesn't already have a .env
Source: ".env.example"; DestDir: "{app}"; DestName: ".env.example"; Flags: ignoreversion
; App icon for window title bar
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
; Install .env.example as .env only if .env doesn't exist yet
Source: ".env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\Edit Configuration"; Filename: "notepad.exe"; Parameters: """{app}\.env"""; Comment: "Edit .env configuration file"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
; Option to launch after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=Setup has finished installing [name] on your computer.%n%nIMPORTANT: Before running the app, edit the .env configuration file in the installation folder with your inverter and Tapo device settings.%n%nThe app may be launched by selecting the installed shortcut.

[Code]
// Open installation folder after install so user can easily find .env
procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Nothing extra needed - the Start Menu "Edit Configuration" shortcut handles this
end;
