#define MyAppName "Cascadeur MCP"
#define MyAppPublisher "cascadeur-complete contributors"
#define MyAppURL "https://github.com/muhwagwa0112/cascadeur-complete"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0-dev"
#endif
#ifndef StageRoot
  #define StageRoot "..\artifacts\stage"
#endif

[Setup]
AppId={{FB57980C-65F0-4CEB-8517-2D170787745D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={localappdata}\CascadeurMCP\cascadeur-complete
DefaultGroupName=Cascadeur MCP
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\artifacts\installer
OutputBaseFilename=Cascadeur-MCP-{#MyAppVersion}-windows-x64-setup
UninstallDisplayIcon={app}\cascadeur-complete.exe
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=no
DisableProgramGroupPage=yes
DisableDirPage=yes
LicenseFile=..\LICENSE
InfoBeforeFile=..\docs\INSTALLER_NOTICE.txt
WizardStyle=modern

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\inventory"
Type: filesandordirs; Name: "{app}\support"
Type: files; Name: "{app}\cascadeur-complete.exe"
Type: filesandordirs; Name: "{localappdata}\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete"
Type: filesandordirs; Name: "{localappdata}\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events"

[Files]
Source: "{#StageRoot}\app\*"; DestDir: "{app}"; Excludes: "policy.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageRoot}\app\policy.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "{#StageRoot}\bridge\cascadeur_complete\*"; DestDir: "{localappdata}\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageRoot}\bridge\cascadeur_complete_events\*"; DestDir: "{localappdata}\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\packaging\upgrade-state.ps1"; Flags: dontcopy
Source: "..\packaging\backup-existing.ps1"; Flags: dontcopy
Source: "..\packaging\restore-existing.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\Verify Cascadeur MCP"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\verify-install.ps1"""; WorkingDir: "{app}"
Name: "{group}\Uninstall Cascadeur MCP"; Filename: "{uninstallexe}"

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\uninstall-hooks.ps1"" -RuntimeRoot ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "CascadeurMCPUnregister"

[Code]
function OpenMaintenanceFile(FileName: String; DesiredAccess, ShareMode: Cardinal;
  SecurityAttributes: THandle; CreationDisposition, FlagsAndAttributes: Cardinal;
  TemplateFile: THandle): THandle;
  external 'CreateFileW@kernel32.dll stdcall setuponly';

function CloseMaintenanceFile(FileHandle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall setuponly';

function MaintenanceLastError: Cardinal;
  external 'GetLastError@kernel32.dll stdcall setuponly';

var
  PostUninstallScript: String;
  PostUninstallOwnership: String;
  MaintenanceHandle: THandle;
  MaintenanceHeld: Boolean;

function AcquireMaintenanceLease: String;
var
  RuntimePath: String;
  ParentPath: String;
  GatePath: String;
  Opened: THandle;
  ErrorCode: Cardinal;
begin
  Result := '';
  if MaintenanceHeld then
    Exit;
  RuntimePath := RemoveBackslash(ExpandFileName(ExpandConstant('{app}')));
  ParentPath := ExtractFileDir(RuntimePath);
  if (ParentPath = '') or (ExtractFileName(RuntimePath) = '') then
  begin
    Result := 'Unable to determine the stable maintenance gate directory.';
    Exit;
  end;
  GatePath := AddBackslash(ParentPath) + '.' + ExtractFileName(RuntimePath) + '.maintenance.lock';
  if not ForceDirectories(ParentPath) then
  begin
    Result := 'Unable to create the maintenance gate directory.';
    Exit;
  end;
  { Parent setup process owns this non-inheritable handle across backup,
    InstallDelete, child hooks, verification and rollback. File existence is
    harmless; only incompatible live sharing handles deny this open. }
  Opened := OpenMaintenanceFile(GatePath, $C0000000, 0, 0, 4, $80, 0);
  if Opened = THandle(-1) then
  begin
    ErrorCode := MaintenanceLastError;
    Result := 'Unable to acquire the maintenance lease. Close the installed runtime and any other installer. Windows error ' + IntToStr(ErrorCode) + '.';
    Exit;
  end;
  MaintenanceHandle := Opened;
  MaintenanceHeld := True;
end;

procedure DeinitializeSetup;
begin
  if MaintenanceHeld then
  begin
    if not CloseMaintenanceFile(MaintenanceHandle) then
      Log('Unable to close the maintenance lease; Windows will release it when Setup exits.');
    MaintenanceHeld := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  BackupScript: String;
  Parameters: String;
begin
  Result := AcquireMaintenanceLease;
  if Result <> '' then
    Exit;
  ExtractTemporaryFile('upgrade-state.ps1');
  ExtractTemporaryFile('backup-existing.ps1');
  ExtractTemporaryFile('restore-existing.ps1');
  BackupScript := ExpandConstant('{tmp}\backup-existing.ps1');
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + BackupScript +
    '" -RuntimeRoot "' + ExpandConstant('{app}') +
    '" -BridgeRoot "' + ExpandConstant('{localappdata}\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete') +
    '" -EventsRoot "' + ExpandConstant('{localappdata}\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events') + '"';
  Parameters := Parameters + ' -TransactionManifest "' + ExpandConstant('{tmp}\cascadeur-mcp-transaction.json') + '"';
  if not Exec('powershell.exe', Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := 'Unable to start the pre-upgrade backup.'
  else if ResultCode <> 0 then
    Result := 'The pre-upgrade backup failed. Installation was not started.';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Parameters: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    PostUninstallScript := ExpandConstant('{tmp}\cascadeur-mcp-post-uninstall.ps1');
    PostUninstallOwnership := ExpandConstant('{tmp}\cascadeur-mcp-ownership.json');
    FileCopy(ExpandConstant('{app}\support\post-uninstall-restore.ps1'), PostUninstallScript, False);
    if FileExists(ExpandConstant('{app}\state\install-ownership.json')) then
      FileCopy(ExpandConstant('{app}\state\install-ownership.json'), PostUninstallOwnership, False);
  end
  else if (CurUninstallStep = usPostUninstall) and FileExists(PostUninstallScript) and
          FileExists(PostUninstallOwnership) then
  begin
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + PostUninstallScript +
      '" -OwnershipPath "' + PostUninstallOwnership +
      '" -RuntimeOwnershipPath "' + ExpandConstant('{app}\state\install-ownership.json') + '"';
    if (not Exec('powershell.exe', Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
       (ResultCode <> 0) then
      SuppressibleMsgBox('Cascadeur MCP was removed, but the pre-install bridge backup could not be restored.',
        mbError, MB_OK, IDOK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  RestoreCode: Integer;
  Parameters: String;
  RestoreParameters: String;
begin
  if CurStep = ssPostInstall then
  begin
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\support\install-hooks.ps1') + '" -RuntimeRoot "' + ExpandConstant('{app}') +
      '" -TransactionManifest "' + ExpandConstant('{tmp}\cascadeur-mcp-transaction.json') + '"';
    if (not Exec('powershell.exe', Parameters, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
       (ResultCode <> 0) then
    begin
      RestoreParameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
        ExpandConstant('{tmp}\restore-existing.ps1') + '" -TransactionManifest "' +
        ExpandConstant('{tmp}\cascadeur-mcp-transaction.json') + '"';
      if (not Exec('powershell.exe', RestoreParameters, '', SW_HIDE, ewWaitUntilTerminated, RestoreCode)) or
         (RestoreCode <> 0) then
        RaiseException('Cascadeur/Codex registration failed and automatic restore failed. The pre-upgrade backup was preserved.')
      else
        RaiseException('Cascadeur/Codex registration failed. Settings were restored from backup.');
    end;

    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\support\verify-install.ps1') + '" -RuntimeRoot "' + ExpandConstant('{app}') + '"';
    if (not Exec('powershell.exe', Parameters, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
       (ResultCode <> 0) then
    begin
      RestoreParameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
        ExpandConstant('{tmp}\restore-existing.ps1') + '" -TransactionManifest "' +
        ExpandConstant('{tmp}\cascadeur-mcp-transaction.json') + '"';
      if (not Exec('powershell.exe', RestoreParameters, '', SW_HIDE, ewWaitUntilTerminated, RestoreCode)) or
         (RestoreCode <> 0) then
        RaiseException('Installed MCP verification failed and automatic restore failed. The pre-upgrade backup was preserved.')
      else
        RaiseException('Installed MCP verification failed. Previous state was restored.');
    end;
  end;
end;
