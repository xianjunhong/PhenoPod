#define AppName "PhenoPod"
#define AppVersion "1.1.1"
#define AppPublisher "JinLab"
#define AppExeName "PhenoPod.exe"

[Setup]
AppId={{E1570C64-1694-4A77-90B2-1D27F1537DD8}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=PhenoPod Intelligent Pod Measurement Platform Setup
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=PhenoPod_Setup_{#AppVersion}
SetupIconFile=icons\PhenoPod.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"; Flags: unchecked

[Files]
Source: "dist\PhenoPod\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function IsMVSInstalled: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{commoncf32}\MVS\Runtime\Win64_x64\MvCameraControl.dll')) or
    FileExists(ExpandConstant('{pf32}\MVS\Applications\Win64\MVS.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not WizardSilent) and (not IsMVSInstalled) then
    MsgBox(
      'Hikvision MVS was not detected. Image import and measurement will still work. Install the official Hikvision MVS package before connecting an industrial camera.',
      mbInformation,
      MB_OK
    );
end;
