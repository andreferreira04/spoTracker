; Stays 0.0.0 in the repo; the CI workflow patches it when building a release
#define AppVersion "0.0.0"
#if AppVersion == "0.0.0"
  #define AppTitle "SpoTracker (Dev)"
#else
  #define AppTitle "SpoTracker"
#endif

[Setup]
AppId={{402327EE-B0CC-4F5E-B760-1E0860434DD0}}
AppName={#AppTitle}
AppVersion={#AppVersion}
DefaultDirName={pf}\SpoTracker
DefaultGroupName=SpoTracker
OutputDir=output
OutputBaseFilename=SpoTrackerInstaller
Compression=lzma
SolidCompression=yes
CloseApplications=force
CloseApplicationsFilter=SpoTracker.exe

[Files]
; Main tracker (onedir build)
Source: "dist\SpoTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
; Start Menu shortcuts
Name: "{group}\SpoTracker";            Filename: "{app}\SpoTracker.exe"
Name: "{group}\Open Report";           Filename: "{userdocs}\SpoTracker\reports\overview.html"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "SpoTracker"; \
    ValueData: """{app}\SpoTracker.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\SpoTracker.exe"; Flags: nowait postinstall skipifsilent; \
    Description: "Start SpoTracker"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM SpoTracker.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
  Result := '';
end;