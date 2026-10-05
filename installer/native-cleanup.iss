#include NativeCleanupInclude

procedure CompleteNativeLegacyCleanup();
var
  PlanPath: String;
  ResultPath: String;
  HelperPath: String;
  Parameters: String;
  ResultCode: Integer;
  ResultText: AnsiString;
begin
  try
    PlanPath := ExpandConstant('{tmp}\native-cleanup-plan.json');
    ResultPath := ExpandConstant('{tmp}\native-cleanup-result.txt');
    HelperPath := ExpandConstant('{tmp}\native-cleanup.ps1');
    ExtractTemporaryFile('native-cleanup.ps1');
    WriteNativeCleanupPlan(PlanPath);
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + HelperPath +
      '" -Root "' + ExpandConstant('{app}') + '" -Plan "' + PlanPath +
      '" -ResultFile "' + ResultPath + '"';
    if not Exec(
      ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode
    ) then begin
      Log('Native legacy cleanup could not start.');
    end;
    if LoadStringFromFile(ResultPath, ResultText) then begin
      Log('Native legacy cleanup: ' + UTF8Decode(ResultText));
    end;
  except
    Log('Native legacy cleanup skipped: ' + GetExceptionMessage());
  end;
end;
