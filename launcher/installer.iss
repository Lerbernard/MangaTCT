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
OutputDir=dist
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

[UninstallDelete]
; what the launcher made after install: fetched app versions, weights, logs
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\state.json"
Type: files; Name: "{app}\update.json"
