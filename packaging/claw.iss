; S-CLAW installer (Inno Setup 6, https://jrsoftware.org/isinfo.php)
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
; The installer's own file name. [Code] needs it too, and a [Setup] directive is not
; a preprocessor variable, so it is defined once here and used in both places.
#define BaseName "S-CLAW-" + Version + "-" + Edition + "-Setup"

[Setup]
; Deliberately the SAME AppId as the "Oluwaseun Claw" releases: Windows then treats
; a new build as an upgrade of the old install rather than a second program, so the
; Start-menu entry and the uninstall entry are replaced instead of duplicated.
AppId={{6E7D7B4A-2D7C-4E0B-9C8F-0C1A5B7E3D21}
AppName=S-CLAW
AppVersion={#Version}
AppVerName=S-CLAW {#Version} ({#Edition})
AppPublisher=Oluwaseun
AppPublisherURL=https://oluwaseun-joshua-site.vercel.app/
AppSupportURL=https://oluwaseun-joshua-site.vercel.app/
AppUpdatesURL=https://oluwaseun-joshua-site.vercel.app/
; Shown in Add/Remove Programs and in the installer's own file properties.
AppCopyright=Copyright (C) 2026 Akintunde Oluwaseun Joshua
DefaultDirName={autopf}\S-CLAW
DefaultGroupName=S-CLAW
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename={#BaseName}
SetupIconFile=..\desktop\src\assets\icon.ico
UninstallDisplayIcon={app}\S-CLAW.exe
Compression=lzma2/normal
SolidCompression=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
LicenseFile=..\LICENSE
#ifdef SliceBytes
; Release builds: split into parts below GitHub's 2 GB per-file limit (Setup.exe + Setup-N.bin, keep together).
DiskSpanning=yes
DiskSliceSize={#SliceBytes}
#elif Edition == "Pro"
DiskSpanning=yes
DiskSliceSize=max
#endif

[Files]
; The whole unpacked app, including resources\backend, engine, tesseract and models.
Source: "{#AppDir}\*"; Excludes: "\resources\models\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Brain files (GGUF) barely compress: store them as they are, which makes building much faster.
Source: "{#AppDir}\resources\models\*"; DestDir: "{app}\resources\models"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression skipifsourcedoesntexist
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\S-CLAW"; Filename: "{app}\S-CLAW.exe"
Name: "{autodesktop}\S-CLAW"; Filename: "{app}\S-CLAW.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\S-CLAW.exe"; Description: "Start S-CLAW"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings, history and downloaded brains in %APPDATA%\S-CLAW are the user's and are kept.
; A previous install kept them in %APPDATA%\OluwaseunClaw; the app moves that folder
; across on first run (claw/config.py), so the uninstaller must not touch either.
Type: filesandordirs; Name: "{app}\resources"

#ifdef SliceBytes
[Code]
// A split installer is useless without all of its parts. Inno's own behaviour is to
// start installing and then ask for a "disk" halfway through, which looks like a fault
// in the app. Check before anything is written and name the file that is missing.
function PartName(I: Integer): String;
begin
  Result := '{#BaseName}' + '-' + IntToStr(I) + '.bin';
end;

function InitializeSetup(): Boolean;
var
  Dir, Missing: String;
  I, Highest: Integer;
begin
  Result := True;
  Dir := ExpandConstant('{src}');
  Highest := 0;
  for I := 1 to 99 do
    if FileExists(Dir + '\' + PartName(I)) then
      Highest := I;
  Missing := '';
  if Highest = 0 then
    Missing := #13#10 + '    ' + PartName(1)
  else
    for I := 1 to Highest do
      if not FileExists(Dir + '\' + PartName(I)) then
        Missing := Missing + #13#10 + '    ' + PartName(I);
  if Missing <> '' then
  begin
    MsgBox('Setup cannot start: these files are missing from this folder:' + #13#10 + Missing + #13#10 + #13#10 +
           'This installer comes in several files. Download all of them from the release into the same folder as ' +
           'Setup.exe, then run Setup.exe again.' + #13#10 + #13#10 +
           'Folder: ' + Dir, mbCriticalError, MB_OK);
    Result := False;
  end;
end;

#endif
