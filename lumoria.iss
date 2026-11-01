; Lumoria Visual FX Engine - Windows installer (Inno Setup 6). Built by build.py, which passes MyVersion.
; Installs dist\Lumoria (the PyInstaller build). Looks, settings and MIDI links live in %APPDATA%\Lumoria and are
; left alone on uninstall, so reinstalling or updating keeps them.

#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

[Setup]
; the AppId must never change: it's how Windows knows a new version updates the old one
AppId={{EC7F39E0-7AAB-46C4-A202-8C1F115AE1E1}
AppName=Lumoria
AppVersion={#MyVersion}
AppVerName=Lumoria Visual FX Engine {#MyVersion}
AppPublisher=Lumoria
DefaultDirName={autopf}\Lumoria
DefaultGroupName=Lumoria
DisableProgramGroupPage=yes
; no admin needed: installs for the current user unless they choose "all users" in the dialog
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=Lumoria-Setup-{#MyVersion}
SetupIconFile=assets\lumoria.ico
UninstallDisplayIcon={app}\Lumoria.exe
UninstallDisplayName=Lumoria Visual FX Engine
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\Lumoria\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; the GPL travels with the program
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Lumoria"; Filename: "{app}\Lumoria.exe"; Comment: "Lumoria Visual FX Engine"; AppUserModelID: "Lumoria.VisualFXEngine"
Name: "{autodesktop}\Lumoria"; Filename: "{app}\Lumoria.exe"; Tasks: desktopicon; AppUserModelID: "Lumoria.VisualFXEngine"
; for testers: runs a few seconds with the AI mask and Spout on, then opens a short report to send back
Name: "{autoprograms}\Lumoria Self-Test"; Filename: "{app}\Lumoria.exe"; Parameters: "--selftest --report"; Comment: "Check Lumoria works on this PC and make a report"

[Run]
Filename: "{app}\Lumoria.exe"; Description: "{cm:LaunchProgram,Lumoria}"; Flags: nowait postinstall skipifsilent
