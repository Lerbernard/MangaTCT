; MangaTCT for Windows - the installer.
;
; Compiled by `.github/workflows/release.yml` with Inno Setup 6:
;     ISCC.exe /DAppVersion=1.0.0 /DStage=stage launcher\installer.iss
;
; `Stage` is a folder the workflow assembled:
;     stage\MangaTCT.exe        the launcher (PyInstaller)
;     stage\runtime\python\     Python with every package installed
;     stage\app\1.0.0\          the app zip unpacked, with .complete inside
;
; It installs PER USER into %LOCALAPPDATA%\MangaTCT - no administrator
; prompt, and the launcher can write there (it swaps app versions in place).
; The model weights are NOT in here; the launcher fetches them on the first
; start from their publishers. NOTICE says why.
;
; Not signed. Windows SmartScreen will say "unrecognised app" until a code
; signing certificate is bought; the download page says so and says what to
; click. The uninstaller removes this folder and nothing else - the person's
; fonts, keys and preferences are in ~\.mangatl and stay.
;
; WHEN THIS RUNS OVER A RUNNING APP. 1.0.2's installer stopped at "Setup was
; unable to automatically close all applications": Windows' Restart Manager
; asks programs to close and the launcher, the editor (python.exe) and the
; window process do not answer it. lee: *"when i download 1.2 it dont update
; 1.2 it reinstalls everything"*. So `PrepareToInstall` below stops
; everything running out of {app} itself, before Setup looks. The app also
; runs this installer by itself now (Settings > Updates > Get the new setup):
; silently, with `/relaunch=1`, which is what starts MangaTCT again at the
; end. The full copy of the runtime is still what an installer does; app
; versions in between come through the launcher, a few megabytes at a time.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Stage
  #define Stage "stage"
#endif

[Setup]
AppId={{7D3E8C1A-5B6F-4E2D-9A1C-3B2A1C0D9E8F}
AppName=MangaTCT
AppVersion={#AppVersion}
AppVerName=MangaTCT {#AppVersion} (beta)
AppPublisher=LMB Technology
AppPublisherURL=https://mangatctproject.web.app
AppSupportURL=https://mangatctproject.web.app/download
DefaultDirName={localappdata}\MangaTCT
DefaultGroupName=MangaTCT
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Relative to THIS FILE's folder, like SetupIconFile below - not to the
; working directory. `dist` alone put the installer in launcher\dist, where
; the workflow's upload pattern (dist\MangaTCT-Setup-*.exe) never looked, and
; Release #5 published nothing. `..\dist` is the repository's dist, beside
; the app zip and the manifest that names it.
OutputDir=..\dist
OutputBaseFilename=MangaTCT-Setup-{#AppVersion}
SetupIconFile=..\static\icon.ico
UninstallDisplayIcon={app}\MangaTCT.exe
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
MinVersion=10.0
LicenseFile=..\LICENSE
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Stage}\MangaTCT.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Stage}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
; which requirements the runtime was built against, so the first start skips pip
Source: "{#Stage}\state.json"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\models"
Name: "{app}\logs"

[Icons]
Name: "{group}\MangaTCT"; Filename: "{app}\MangaTCT.exe"
Name: "{group}\Uninstall MangaTCT"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MangaTCT"; Filename: "{app}\MangaTCT.exe"; Tasks: desktopicon

[Registry]
; .tctp - a chapter. Double-click opens MangaTCT; the launcher passes the
; path on to the editor once that is wired (it is accepted and ignored now).
Root: HKCU; Subkey: "Software\Classes\.tctp"; ValueType: string; ValueName: ""; ValueData: "MangaTCT.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\MangaTCT.Project"; ValueType: string; ValueName: ""; ValueData: "MangaTCT chapter"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\MangaTCT.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\MangaTCT.exe,0"
Root: HKCU; Subkey: "Software\Classes\MangaTCT.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MangaTCT.exe"" ""%1"""

[Run]
Filename: "{app}\MangaTCT.exe"; Description: "Start MangaTCT"; Flags: nowait postinstall skipifsilent
; The app updating itself: the setup was run silently by MangaTCT with
; /relaunch=1, and the person is waiting for it to come back.
Filename: "{app}\MangaTCT.exe"; Flags: nowait skipifnotsilent; Check: Relaunch

[UninstallDelete]
; what the launcher made after install: fetched app versions, weights, logs
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\state.json"
Type: files; Name: "{app}\update.json"

[Code]
{ Everything running out of the install folder - MangaTCT.exe, the runtime's
  python.exe (the editor, the window), pip - stopped, so the files they hold
  can be replaced. PowerShell because it is on every Windows this installs
  on and can match a process by the path of its exe; taskkill can only match
  by name, and "python.exe" is not ours alone. Nothing here is allowed to
  fail the install: if PowerShell is missing, Setup's own check runs next
  and says what it always said. }
procedure StopTheApp(Folder: String);
var
  Cmd: String;
  Code: Integer;
begin
  if Copy(Folder, Length(Folder), 1) <> '\' then
    Folder := Folder + '\';
  Cmd := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
    '$app = ''' + Folder + '''; ' +
    'Get-Process -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -and $_.Path.StartsWith($app, [System.StringComparison]::OrdinalIgnoreCase) } | ' +
    'Stop-Process -Force -ErrorAction SilentlyContinue"';
  if Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Sleep(1500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  StopTheApp(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopTheApp(ExpandConstant('{app}'));
end;

{ /relaunch=1 on the command line: start MangaTCT when the silent install
  is done. Only the app itself passes it. }
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
