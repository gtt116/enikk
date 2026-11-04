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
#define InterceptionDir "tools\Interception\Interception"
#define InterceptionInstaller "command line installer\install-interception.exe"
#define InterceptionDll "library\x64\interception.dll"
#if FileExists("..\" + InterceptionDir + "\" + InterceptionInstaller) && FileExists("..\" + InterceptionDir + "\" + InterceptionDll) && FileExists("..\" + InterceptionDir + "\licenses\non-commercial-usage\LGPL 3.0.txt")
  #define IncludeInterception
#endif

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
#ifdef IncludeInterception
english.InstallInterception=Install the optional Interception mouse driver
english.InterceptionInstallFailed=Interception setup failed (code %1). Enikk setup will continue.
english.InterceptionRestartRequired=Restart Windows before using the Interception mouse driver.
chinesesimplified.InstallInterception=安装可选的 Interception 鼠标驱动
chinesesimplified.InterceptionInstallFailed=Interception 驱动安装失败（代码 %1）。Enikk 将继续安装。
chinesesimplified.InterceptionRestartRequired=请重启 Windows 后再使用 Interception 鼠标驱动。
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
#ifdef IncludeInterception
Name: "interception"; Description: "{cm:InstallInterception}"; Flags: unchecked checkedonce
#endif

[Files]
; PyInstaller output: enikk.exe + _internal/
Source: "..\dist\enikk\enikk.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\enikk\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef IncludeInterception
Source: "..\{#InterceptionDir}\{#InterceptionInstaller}"; DestDir: "{app}\{#InterceptionDir}\command line installer"; Tasks: interception; Flags: ignoreversion
Source: "..\{#InterceptionDir}\{#InterceptionDll}"; DestDir: "{app}\{#InterceptionDir}\library\x64"; Tasks: interception; Flags: ignoreversion
Source: "..\{#InterceptionDir}\licenses\*"; DestDir: "{app}\{#InterceptionDir}\licenses"; Tasks: interception; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

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
#ifdef IncludeInterception
function HasInterceptionFilter(const ClassId, DriverName: String): Boolean;
var
  Filters: String;
  ClassKey: String;
begin
  ClassKey := 'SYSTEM\CurrentControlSet\Control\Class\' + Chr(123) + ClassId + Chr(125);
  Result := RegQueryMultiStringValue(HKLM, ClassKey, 'UpperFilters', Filters) and
    (Pos(#0 + DriverName + #0, #0 + Lowercase(Filters) + #0) > 0);
end;

function InterceptionInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{sys}\drivers\mouse.sys')) and
    FileExists(ExpandConstant('{sys}\drivers\keyboard.sys')) and
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\mouse') and
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\keyboard') and
    HasInterceptionFilter('4d36e96f-e325-11ce-bfc1-08002be10318', 'mouse') and
    HasInterceptionFilter('4d36e96b-e325-11ce-bfc1-08002be10318', 'keyboard');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  InstallerPath, Details, MessageText: String;
  ResultCode: Integer;
  Output: TExecOutput;
  Started: Boolean;
begin
  if (CurStep <> ssPostInstall) or not WizardIsTaskSelected('interception') then
    Exit;
  if InterceptionInstalled() then
  begin
    Log('Interception drivers are already installed. Skipping driver installation.');
    Exit;
  end;

  InstallerPath := ExpandConstant('{app}\{#InterceptionDir}\{#InterceptionInstaller}');
  ResultCode := 0;
  try
    Started := ExecAndCaptureOutput(InstallerPath, '/install', ExtractFileDir(InstallerPath),
      SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode, Output);
    if Started then
      Details := Trim(StringJoin(#13#10, Output.StdOut) + #13#10 +
        StringJoin(#13#10, Output.StdErr))
    else
      Details := SysErrorMessage(ResultCode);
  except
    Started := False;
    Details := GetExceptionMessage;
  end;
  if Details <> '' then
    Log('Interception installer output: ' + Details);

  if Started and (ResultCode = 0) then
  begin
    Log('Interception setup succeeded. Restart Windows before using the driver.');
    SuppressibleMsgBox(CustomMessage('InterceptionRestartRequired'), mbInformation, MB_OK, IDOK);
  end
  else
  begin
    Log(Format('Interception setup failed (code %d).', [ResultCode]));
    MessageText := FmtMessage(CustomMessage('InterceptionInstallFailed'), [IntToStr(ResultCode)]);
    if Details <> '' then
      MessageText := MessageText + #13#10 + #13#10 + Details;
    SuppressibleMsgBox(MessageText, mbError, MB_OK, IDOK);
  end;
end;

#endif

function GetInstalledVersion(): String;
var
  key: String;
  ver: String;
begin
  Result := '';
  key := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\' +
         Chr(123) + 'C5C5100B-32E9-4826-B744-A0B60A4A60F4' + Chr(125) + '_is1';
  if RegQueryStringValue(HKLM, key, 'DisplayVersion', ver) then
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
