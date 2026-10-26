; Oluwaseun Claw installer (Inno Setup 6, https://jrsoftware.org/isinfo.php)
; Built by scripts\build-release.ps1, which passes:
;   /DEdition=Standard|Pro  /DAppDir=<electron-builder win-unpacked folder>  /DVersion=x.y.z  /DOutDir=<folder>
;
; Size: Inno Setup keeps everything inside Setup.exe up to about 4.2 GB. The Standard
; edition (~3.6 GB) fits in one file. The Pro edition's brain is bigger, so it is split
; into Setup.exe plus Setup-N.bin parts that must stay in the same folder (DiskSpanning).

#ifndef Edition
  #define Edition "Standard"
#endif
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6E7D7B4A-2D7C-4E0B-9C8F-0C1A5B7E3D21}
AppName=Oluwaseun Claw
AppVersion={#Version}
AppVerName=Oluwaseun Claw {#Version} ({#Edition})
AppPublisher=Oluwaseun Claw contributors
DefaultDirName={autopf}\Oluwaseun Claw
DefaultGroupName=Oluwaseun Claw
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=OluwaseunClaw-{#Version}-{#Edition}-Setup
SetupIconFile=..\desktop\src\assets\icon.ico
UninstallDisplayIcon={app}\Oluwaseun Claw.exe
Compression=lzma2/normal
SolidCompression=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
LicenseFile=..\LICENSE
#if Edition == "Pro"
DiskSpanning=yes
DiskSliceSize=max
#endif

[Files]
; The whole unpacked app, including resources\backend, engine, tesseract and models.
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Oluwaseun Claw"; Filename: "{app}\Oluwaseun Claw.exe"
Name: "{autodesktop}\Oluwaseun Claw"; Filename: "{app}\Oluwaseun Claw.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Oluwaseun Claw.exe"; Description: "Start Oluwaseun Claw"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings, history and downloaded brains in %APPDATA%\OluwaseunClaw are the user's and are kept.
Type: filesandordirs; Name: "{app}\resources"
