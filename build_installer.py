import os
import subprocess
import glob
from pathlib import Path

root = Path(__file__).parent.resolve()
iss_file = root / "quill_setup.iss"

# Generate the Inno Setup script
iss_content = f'''
[Setup]
AppName=Quill-Cowork
AppVersion=0.3.0
DefaultDirName={{autopf}}\\Quill-Cowork
DefaultGroupName=Quill-Cowork
UninstallDisplayIcon={{app}}\\start_quill.bat
Compression=lzma2
SolidCompression=yes
OutputDir={root}\\installer_output
OutputBaseFilename=Quill-Cowork-Setup
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Files]
Source: "{root}\\backend\\*"; DestDir: "{{app}}\\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "venv"
Source: "{root}\\rust_core\\*"; DestDir: "{{app}}\\rust_core"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "target"
Source: "{root}\\installer.ps1"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{root}\\README.md"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{root}\\LICENSE"; DestDir: "{{app}}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{{app}}\\installer.ps1"" -InstallPath ""{{app}}"""; StatusMsg: "Downloading models, setting up Python venv, and compiling Rust (this may take 10-15 minutes)..."; Flags: waituntilterminated
'''

iss_file.write_text(iss_content, encoding="utf-8")
print(f"[*] Generated {iss_file.name}")

# Search for ISCC.exe on C: and D: drives
iscc_patterns = [
    r"C:\Program Files (x86)\Inno Setup*\ISCC.exe",
    r"C:\Program Files\Inno Setup*\ISCC.exe",
    r"C:\Users\*\AppData\Local\Programs\Inno Setup*\ISCC.exe",
    r"D:\Inno Setup*\ISCC.exe",
    r"D:\Program Files*\Inno Setup*\ISCC.exe",
    r"D:\*\Inno Setup*\ISCC.exe"
]

iscc_paths = []
for pattern in iscc_patterns:
    iscc_paths.extend(glob.glob(pattern))

iscc = None
if iscc_paths:
    iscc = iscc_paths[0]

# If it still can't find it, ask the user
if not iscc:
    print("[-] Could not find ISCC.exe automatically.")
    user_path = input("Paste the full path to ISCC.exe (e.g., D:\\Inno Setup 7\\ISCC.exe), or press Enter to skip: ").strip('"').strip("'")
    if user_path and os.path.exists(user_path):
        iscc = user_path

# Compile
if iscc:
    print(f"[*] Found Inno Setup Compiler at: {iscc}")
    print("[*] Compiling standalone installer (this takes about 10 seconds)...")
    result = subprocess.run([iscc, str(iss_file)], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"\n[+] SUCCESS! Installer created at: {root}\\installer_output\\Quill-Cowork-Setup.exe")
    else:
        print(f"[-] Compilation failed:\n{result.stdout}\n{result.stderr}")
else:
    print("[-] Skipping compilation. Inno Setup compiler not found.")