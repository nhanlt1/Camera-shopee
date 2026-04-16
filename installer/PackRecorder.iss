#define MyAppName "Pack Recorder"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\\dist\\PackRecorder"
#endif

[Setup]
AppId={{4C9D4D92-A30C-4EFA-9A46-9D4F7CC0E11B}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher=PackRecorder
DefaultDirName={autopf}\Pack Recorder
DefaultGroupName=Pack Recorder
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=PackRecorder-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
SetupIconFile=..\logo.ico
UninstallDisplayIcon={app}\PackRecorder.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Pack Recorder"; Filename: "{app}\PackRecorder.exe"
Name: "{autodesktop}\Pack Recorder"; Filename: "{app}\PackRecorder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PackRecorder.exe"; Description: "Launch Pack Recorder"; Flags: nowait postinstall skipifsilent
