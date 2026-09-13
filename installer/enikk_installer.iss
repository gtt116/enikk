; Inno Setup script for Enikk — Open-source Computer Use Agent
; Build: pyinstaller enikk.spec, then compile this .iss with ISCC.exe
; Run from project root: ISCC.exe installer\enikk_installer.iss

#define MyAppName "Enikk"
#ifndef MyAppVersion
  #error "MyAppVersion must be defined: pass /DMyAppVersion=<version> to ISCC"
#endif
#define MyAppPublisher "gtt116"
#define MyAppURL "https://github.com/gtt116/enikk"
#define MyAppExeName "enikk.exe"

[Setup]
; App identity
AppId={{C5C5100B-32E9-4826-B744-A0B60A4A60F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Install location
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; Output
OutputDir=..\installer_output
OutputBaseFilename=Enikk-{#MyAppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes

; UAC — Enikk needs admin to control other windows
PrivilegesRequired=admin

; UI
WizardStyle=modern
SetupIconFile=..\enikk\static\enikk-logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; Size estimate (~431 MB)
ExtraDiskSpaceRequired=500000000

; License
LicenseFile=..\LICENSE

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.CreateDesktopIcon=Create a &desktop icon
english.AdditionalIcons=Additional icons:
english.LaunchProgram=Launch {#MyAppName}
chinesesimplified.CreateDesktopIcon=创建桌面快捷方式(&D)
chinesesimplified.AdditionalIcons=附加图标:
chinesesimplified.LaunchProgram=启动 {#MyAppName}
english.StopEnikkPrompt=Enikk is currently running. End it now to continue, or choose No to cancel setup.
english.StopEnikkCancelled=Setup cancelled: Enikk is still running.
chinesesimplified.StopEnikkPrompt=Enikk 正在运行，是否结束进程后继续安装？选「否」将取消安装。
chinesesimplified.StopEnikkCancelled=已取消安装：Enikk 仍在运行。
english.UpgradePromptPrefix=Existing Enikk v
english.UpgradePromptSuffix= will be upgraded to v
chinesesimplified.UpgradePromptPrefix=检测到已安装的 Enikk v
chinesesimplified.UpgradePromptSuffix=，将升级到 v

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller output: enikk.exe + _internal/
Source: "..\dist\enikk\enikk.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\enikk\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Launch after install — wait until idle to avoid file lock issues
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: postinstall skipifsilent shellexec waituntilidle

[UninstallDelete]
; Clean up logs and crash dumps
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\enikk_crash.log"

[Code]
function GetInstalledVersion(): String;
var
  ver: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{C5C5100B-32E9-4826-B744-A0B60A4A60F4}}_is1', 'DisplayVersion', ver) then
    Result := ver;
end;

function InitializeSetup(): Boolean;
var
  installed: String;
begin
  Result := True;
  installed := GetInstalledVersion();
  if installed = '' then
    Exit;
  if CompareText(installed, '{#MyAppVersion}') <> 0 then
  begin
    if MsgBox(CustomMessage('UpgradePromptPrefix') + installed + #13#10 +
              CustomMessage('UpgradePromptSuffix') + '{#MyAppVersion}',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

function IsEnikkRunning(): Boolean;
var
  exe, tmp: String;
begin
  exe := ExpandConstant('{app}\{#MyAppExeName}');
  Result := False;
  if not FileExists(exe) then
    Exit;
  // A running exe holds a lock that forbids rename; if we can rename it back
  // and forth then it is not running.
  tmp := exe + '.lock-check';
  if RenameFile(exe, tmp) then
    RenameFile(tmp, exe)
  else
    Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if not IsEnikkRunning() then
    Exit;
  if MsgBox(CustomMessage('StopEnikkPrompt'), mbConfirmation, MB_YESNO) = IDYES then
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM enikk.exe', '',
         SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end
  else
    Result := CustomMessage('StopEnikkCancelled');
end;
