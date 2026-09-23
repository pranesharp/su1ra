#define AppName "Su1ra"
#define AppVersion "0.2.0"
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
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "installollama"; Description: "Download and install Ollama (recommended - required to run models)"; GroupDescription: "Requirements:"; Flags: checkedonce
Name: "openmodellib"; Description: "Open the Ollama model library in your browser after setup (browse what to pull with /models get in-app)"; GroupDescription: "Requirements:"; Flags: unchecked
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\packaging\dist\Su1ra\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "https://ollama.com/download/OllamaSetup.exe"; DestDir: "{tmp}"; Flags: download dontcopy; Tasks: installollama

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\su1ra.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\su1ra.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\OllamaSetup.exe"; StatusMsg: "Installing Ollama..."; Tasks: installollama
Filename: "https://ollama.com/search"; Flags: shellexec runasoriginaluser postinstall; Tasks: openmodellib
Filename: "{app}\su1ra.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
