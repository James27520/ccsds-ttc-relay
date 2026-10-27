function Resolve-AddaToolDirectory {
 param([string]$Directory,[string]$Variable,[string]$Executable)
 if(-not $Directory){$Directory=[Environment]::GetEnvironmentVariable($Variable)}
 if(-not $Directory){
  $taskCommand=Get-Command $Executable -ErrorAction SilentlyContinue
  if($taskCommand){$Directory=Split-Path -Parent $taskCommand.Source}
 }
 if(-not $Directory -or -not (Test-Path -LiteralPath (Join-Path $Directory $Executable))){
  throw "Supply the tool bin directory or set $Variable; cannot locate $Executable"
 }
 return (Resolve-Path -LiteralPath $Directory).Path
}
