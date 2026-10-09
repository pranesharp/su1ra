#define AppName "Su1ra"
#define AppVersion "0.3.0"
#define AppPublisher "ganpat"

[Setup]
AppId={{7C3A9E12-5B44-4F8A-9A21-SU1RA0LOCAL1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=Su1ra-setup-x64
SetupIconFile=..\su1ra.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "openmodellib"; Description: "Open the Ollama model library in your browser after setup (browse what to pull with /models get in-app)"; GroupDescription: "Requirements:"; Flags: unchecked
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\packaging\dist\Su1ra\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\su1ra.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\su1ra.exe"; Tasks: desktopicon

[Run]
Filename: "https://ollama.com/search"; Flags: shellexec runasoriginaluser postinstall; Tasks: openmodellib
Filename: "{app}\su1ra.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\ollama"; Check: NeedsAddOllamaPath

[Code]
function NeedsAddOllamaPath(): Boolean;
var
  OrigPath, Needle: string;
begin
  Needle := ';' + Lowercase(ExpandConstant('{app}\ollama')) + ';';
  if RegQueryStringValue(HKCU, 'Environment', 'Path', OrigPath) then
    Result := Pos(Needle, ';' + Lowercase(OrigPath) + ';') = 0
  else
    Result := True;
end;

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
