; LumaTRX Visual FX Engine - Windows installer (Inno Setup 6). Built by build.py, which passes MyVersion.
; Installs dist\LumaTRX (the PyInstaller build). Looks, settings and MIDI links live in %APPDATA%\LumaTRX and are
; left alone on uninstall, so reinstalling or updating keeps them.

#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

[Setup]
; the AppId must never change: it's how Windows knows a new version updates the old one
AppId={{EC7F39E0-7AAB-46C4-A202-8C1F115AE1E1}
AppName=LumaTRX
AppVersion={#MyVersion}
AppVerName=LumaTRX Visual FX Engine {#MyVersion}
AppPublisher=LumaTRX
DefaultDirName={autopf}\LumaTRX
DefaultGroupName=LumaTRX
DisableProgramGroupPage=yes
; it was called Lumoria: an update installs into the new LumaTRX folder rather than the old one (see InstallDelete)
UsePreviousAppDir=no
; no admin needed: installs for the current user unless they choose "all users" in the dialog
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=LumaTRX-Setup-{#MyVersion}
SetupIconFile=assets\lumatrx.ico
UninstallDisplayIcon={app}\LumaTRX.exe
UninstallDisplayName=LumaTRX Visual FX Engine
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; the program as it was installed under its old name, Lumoria (its looks and settings in %APPDATA%\Lumoria are
; left alone: LumaTRX copies them over the first time it starts)
Type: filesandordirs; Name: "{autopf}\Lumoria"
Type: files; Name: "{autoprograms}\Lumoria.lnk"
Type: files; Name: "{autoprograms}\Lumoria Self-Test.lnk"
Type: files; Name: "{autodesktop}\Lumoria.lnk"

[Files]
Source: "dist\LumaTRX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; the GPL travels with the program
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\LumaTRX"; Filename: "{app}\LumaTRX.exe"; Comment: "LumaTRX Visual FX Engine"; AppUserModelID: "LumaTRX.VisualFXEngine"
Name: "{autodesktop}\LumaTRX"; Filename: "{app}\LumaTRX.exe"; Tasks: desktopicon; AppUserModelID: "LumaTRX.VisualFXEngine"
; for testers: runs a few seconds with the AI mask and Spout on, then opens a short report to send back
Name: "{autoprograms}\LumaTRX Self-Test"; Filename: "{app}\LumaTRX.exe"; Parameters: "--selftest --report"; Comment: "Check LumaTRX works on this PC and make a report"

[Run]
Filename: "{app}\LumaTRX.exe"; Description: "{cm:LaunchProgram,LumaTRX}"; Flags: nowait postinstall skipifsilent
