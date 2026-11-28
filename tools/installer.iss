; Inno Setup script for the Windows installer. tools/build_desktop.py passes in the version, the built app folder and where to write the file:
;   ISCC /DAppVersion=1.2 /DSourceDir=dist\app\"Personal Finance Ledger" /DOutDir=dist /DIconFile=assets\icon.ico tools\installer.iss
; It installs for the current person only (no administrator password) and never touches the numbers, which live in
; %APPDATA%\Personal Finance Ledger\My Ledger Data. Uninstalling leaves that folder alone too.
#define AppName "Personal Finance Ledger"
#define AppExe "Personal Finance Ledger.exe"

[Setup]
AppId={{6C3E1C52-7B0B-4C57-9B7E-6B7C5A1F2D10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Personal Finance Ledger
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=Personal-Finance-Ledger-v{#AppVersion}-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start the ledger when I sign in to Windows (it waits in the tray)"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure StopRunningApp();
var R: Integer;
begin
  Exec('taskkill', '/F /IM "{#AppExe}"', '', SW_HIDE, ewWaitUntilTerminated, R);  // it hides in the tray, so close it before replacing its files
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp();
  Result := True;
end;
