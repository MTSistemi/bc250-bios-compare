; Installer for BC-250 BIOS Compare
; Built with:  python build.py --setup

#define Name "BC-250 BIOS Compare"
#define Version "1.0.0"
#define Publisher "MTSistemi"
#define Executable "Bc250BiosCompare.exe"

[Setup]
AppId={{3F8D91A2-64C7-4E15-B0A9-BC250MENU001}
AppName={#Name}
AppVersion={#Version}
AppPublisher={#Publisher}
DefaultDirName={autopf}\Bc250BiosCompare
DefaultGroupName={#Name}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=Bc250BiosCompare-Setup-{#Version}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=emulator.ico
UninstallDisplayIcon={app}\{#Executable}
; No administrator rights needed: this program only READS, it touches no chip.
; Asking for them would be asking for more than the job requires.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[CustomMessages]
en.DesktopIcon=Create a desktop shortcut
it.DesktopIcon=Crea un collegamento sul desktop

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#Executable}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#Name}"; Filename: "{app}\{#Executable}"
Name: "{autodesktop}\{#Name}"; Filename: "{app}\{#Executable}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Executable}"; Description: "{cm:LaunchProgram,{#Name}}"; Flags: nowait postinstall skipifsilent
