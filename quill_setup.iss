
[Setup]
AppName=Quill-Cowork
AppVersion=0.3.0
DefaultDirName={autopf}\Quill-Cowork
DefaultGroupName=Quill-Cowork
UninstallDisplayIcon={app}\start_quill.bat
Compression=lzma2
SolidCompression=yes
OutputDir=D:\quill-cowork\installer_output
OutputBaseFilename=Quill-Cowork-Setup
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Files]
Source: "D:\quill-cowork\backend\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "venv"
Source: "D:\quill-cowork\rust_core\*"; DestDir: "{app}\rust_core"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "target"
Source: "D:\quill-cowork\installer.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "D:\quill-cowork\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "D:\quill-cowork\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer.ps1"" -InstallPath ""{app}"""; StatusMsg: "Downloading models, setting up Python venv, and compiling Rust (this may take 10-15 minutes)..."; Flags: waituntilterminated
