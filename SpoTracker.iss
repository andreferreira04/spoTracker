; Stays 0.0.0 in the repo; the CI workflow patches it when building a release
#define AppVersion "0.0.0"
#if AppVersion == "0.0.0"
  #define AppTitle "SpoTracker (Dev)"
#else
  #define AppTitle "SpoTracker"
#endif
; File version resources must be numeric (a tag like v1.2.0-beta -> 1.2.0)
#define NumericVersion Copy(AppVersion, 1, Pos("-", AppVersion + "-") - 1)

[Setup]
AppId={{402327EE-B0CC-4F5E-B760-1E0860434DD0}}
AppName={#AppTitle}
AppVersion={#AppVersion}
AppVerName={#AppTitle} {#AppVersion}
AppPublisher=SpoTracker
VersionInfoVersion={#NumericVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoDescription={#AppTitle} {#AppVersion} Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\SpoTracker.exe
WizardStyle=modern
; Show the welcome page so the large logo appears as soon as setup opens
DisableWelcomePage=no
WizardImageFile=assets\wizard-large-164.bmp,assets\wizard-large-328.bmp
WizardSmallImageFile=assets\wizard-small-55.bmp,assets\wizard-small-110.bmp
DefaultDirName={pf}\SpoTracker
DefaultGroupName=SpoTracker
OutputDir=output
OutputBaseFilename=SpoTrackerInstaller-{#AppVersion}
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
procedure InitializeWizard();
var
  VersionLabel: TNewStaticText;
begin
  // Version shown in the bottom-left corner of every wizard page
  VersionLabel := TNewStaticText.Create(WizardForm);
  VersionLabel.Parent := WizardForm;
  VersionLabel.Caption := 'v{#AppVersion}';
  VersionLabel.Font.Color := clGrayText;
  VersionLabel.Left := ScaleX(16);
  VersionLabel.Top := WizardForm.CancelButton.Top +
    (WizardForm.CancelButton.Height - VersionLabel.Height) div 2;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM SpoTracker.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
  Result := '';
end;