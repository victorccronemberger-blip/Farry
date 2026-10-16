#ifndef LauncherVersion
  #error LauncherVersion is required
#endif
#ifndef ArtifactDir
  #error ArtifactDir is required
#endif

[Setup]
AppId={{58925A2D-36D4-4FE6-BC5E-B94327075C2F}
AppName=Farry - QMoney
AppVersion={#LauncherVersion}
AppPublisher=Farry
AppPublisherURL=https://lightcyan-wolf-956118.hostingersite.com/
AppSupportURL=https://lightcyan-wolf-956118.hostingersite.com/
SetupIconFile=..\client\desktop\resources\qmoney.ico
DefaultDirName={localappdata}\Farry
DisableDirPage=yes
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=Local\FarryLauncher
SetupMutex=Local\FarrySetup
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\FarryLauncher.exe
OutputDir={#ArtifactDir}
OutputBaseFilename=FarrySetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
#ifdef InternalSigning
SignTool=farry
SignedUninstaller=yes
SignToolRunMinimized=yes
#endif

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "{#ArtifactDir}\FarryLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Farry - QMoney"; Filename: "{app}\FarryLauncher.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Farry - QMoney"; Filename: "{app}\FarryLauncher.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FarryLauncher.exe"; Description: "Abrir Farry para instalar ou atualizar QMoney"; Flags: nowait postinstall skipifsilent

; No recursive uninstall rules: versions, pointers and QMoney data are preserved.
[Code]
function InitializeSetup(): Boolean;
var
  Release: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release);
  if Result then Result := Release >= 528040;
  if not Result then
    MsgBox('Este instalador requer o .NET Framework 4.8. Instale-o pelo Windows Update ou pelo site da Microsoft.', mbError, MB_OK);
end;
