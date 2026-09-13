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
english.DeleteUserDataPrompt=Also delete user data (configuration, model weights, sessions)? This cannot be undone.
chinesesimplified.DeleteUserDataPrompt=是否同时删除用户数据（配置、模型权重、会话记录）？此操作不可恢复。

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
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: postinstall skipifsilent waituntilidle

[UninstallDelete]
; Clean up logs and crash dumps
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\enikk_crash.log"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox(CustomMessage('DeleteUserDataPrompt') + #13#10#13#10 +
              ExpandConstant('{localappdata}\Enikk'),
              mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\Enikk'), True, True, True);
  end;
end;
