; Inno Setup script for Siftwell (Windows). Per-user install, no administrator prompt.
;
;   ISCC.exe installer\siftwell.iss                       (after the PyInstaller build: dist\Siftwell\)
;   ISCC.exe /DBundleDir=C:\out\dist\Siftwell /DOutDir=C:\out installer\siftwell.iss
;
; Output: Siftwell-Setup-<version>.exe, with <version> read from the VERSION file (or /DAppVersion=x.y.z).
; Written to work with Inno Setup 6.x and newer.

#ifndef AppVersion
  #define VerFile FileOpen(SourcePath + "..\VERSION")
  #define AppVersion FileRead(VerFile)
  #expr FileClose(VerFile)
#endif
#ifndef BundleDir
  #define BundleDir SourcePath + "..\dist\Siftwell"
#endif
#ifndef OutDir
  #define OutDir SourcePath + "..\dist"
#endif

[Setup]
; Never change AppId: it is how a new version finds and upgrades the one already installed.
AppId={{7C3E9A52-4B1D-4E8F-9A6B-2D5F81C0E347}
AppName=Siftwell
AppVersion={#AppVersion}
AppVerName=Siftwell {#AppVersion}
AppPublisher=Siftwell
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Siftwell
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=Siftwell-Setup-{#AppVersion}
SetupIconFile={#SourcePath}..\assets\brand\siftwell.ico
UninstallDisplayIcon={app}\Siftwell.exe
UninstallDisplayName=Siftwell
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; An upgrade closes a running Siftwell first (see PrepareToInstall; Restart Manager catches anything left over).
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Siftwell shortcut on my desktop"; Flags: unchecked

[InstallDelete]
; Old program files are replaced wholesale on upgrade (never touches the user's data, which lives elsewhere).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Siftwell"; Filename: "{app}\Siftwell.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Siftwell"; Filename: "{app}\Siftwell.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Siftwell.exe"; Description: "Launch Siftwell"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
var
  RemoveData: Boolean;

function DataDir: String;
begin
  { Same place the app uses (paths.py): JOBBOARD_DATA if set, else %APPDATA%\JobBoard. }
  Result := GetEnv('JOBBOARD_DATA');
  if Result = '' then
    Result := ExpandConstant('{userappdata}\JobBoard');
end;

function HasSwitch(Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then
      Result := True;
end;

procedure StopSiftwell(AppDir: String);
var
  Exe: String;
  Code: Integer;
begin
  { Siftwell.exe --stop ends this person's running Siftwell (window, tray, server and any job it started). }
  Exe := AddBackslash(AppDir) + 'Siftwell.exe';
  if FileExists(Exe) then
    Exec(Exe, '--stop', AppDir, SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  StopSiftwell(ExpandConstant('{app}'));
end;

procedure RemoveOwnStartupShortcut;
var
  Lnk, Cmd: String;
  Code: Integer;
begin
  { Siftwell's "start at sign-in" shortcut, but only when it points into this install. }
  Lnk := ExpandConstant('{userstartup}\Siftwell.lnk');
  if not FileExists(Lnk) then
    Exit;
  Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(''LNK''); ' +
         'if ($s.TargetPath -like ''APP*'') { Remove-Item -LiteralPath ''LNK'' -Force }"';
  StringChangeEx(Cmd, 'LNK', Lnk, True);
  StringChangeEx(Cmd, 'APP', ExpandConstant('{app}\'), True);
  Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function InitializeUninstall(): Boolean;
var
  F: TSetupForm;
  Msg: TNewStaticText;
  Cb: TNewCheckBox;
  Ok, Cancel: TNewButton;
begin
  Result := True;
  RemoveData := False;
  if UninstallSilent then
  begin
    { Silent uninstall keeps the data unless asked: Siftwell-uninstaller /VERYSILENT /REMOVEDATA }
    RemoveData := HasSwitch('/REMOVEDATA');
  end
  else
  begin
    F := TSetupForm.Create(nil);
    try
      F.Caption := 'Uninstall Siftwell';
      F.BorderStyle := bsDialog;
      F.Position := poScreenCenter;
      F.ClientWidth := ScaleX(440);
      F.ClientHeight := ScaleY(170);

      Msg := TNewStaticText.Create(F);
      Msg.Parent := F;
      Msg.Left := ScaleX(16);
      Msg.Top := ScaleY(16);
      Msg.Width := F.ClientWidth - ScaleX(32);
      Msg.AutoSize := False;
      Msg.WordWrap := True;
      Msg.Height := ScaleY(60);
      Msg.Caption := 'Siftwell will be removed from this computer. Your profiles, resumes, ratings and settings are kept ' +
                     'in your user folder, so installing Siftwell again later picks up where you left off.';

      Cb := TNewCheckBox.Create(F);
      Cb.Parent := F;
      Cb.Left := ScaleX(16);
      Cb.Top := Msg.Top + Msg.Height + ScaleY(8);
      Cb.Width := F.ClientWidth - ScaleX(32);
      Cb.Caption := 'Also remove my Siftwell data (cannot be undone)';
      Cb.Checked := False;

      Ok := TNewButton.Create(F);
      Ok.Parent := F;
      Ok.Caption := 'Uninstall';
      Ok.ModalResult := mrOk;
      Ok.Default := True;
      Ok.Width := ScaleX(90);
      Ok.Height := ScaleY(26);
      Ok.Left := F.ClientWidth - ScaleX(16) - Ok.Width * 2 - ScaleX(8);
      Ok.Top := F.ClientHeight - ScaleY(16) - Ok.Height;

      Cancel := TNewButton.Create(F);
      Cancel.Parent := F;
      Cancel.Caption := 'Cancel';
      Cancel.ModalResult := mrCancel;
      Cancel.Cancel := True;
      Cancel.Width := Ok.Width;
      Cancel.Height := Ok.Height;
      Cancel.Left := F.ClientWidth - ScaleX(16) - Cancel.Width;
      Cancel.Top := Ok.Top;

      if F.ShowModal = mrOk then
        RemoveData := Cb.Checked
      else
        Result := False;
    finally
      F.Free;
    end;
  end;
  if Result then
    StopSiftwell(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  D: String;
begin
  if CurUninstallStep = usUninstall then
    RemoveOwnStartupShortcut
  else if CurUninstallStep = usPostUninstall then
  begin
    { The user's data is deleted only when they ticked the box. }
    if RemoveData then
    begin
      D := RemoveBackslash(DataDir);
      if (Length(D) > 12) and DirExists(D) then
        DelTree(D, True, True, True);
    end;
  end;
end;
