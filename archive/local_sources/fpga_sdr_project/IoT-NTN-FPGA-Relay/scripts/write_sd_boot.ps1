<#
  写SD卡BOOT.ps1 -- 把转发器启动镜像写入 SD 卡（带自动备份与校验）

  用法：
     右键"使用 PowerShell 运行"
     或： powershell -ExecutionPolicy Bypass -File 写SD卡BOOT.ps1

  做四件事：
     1. 列出可移动磁盘，让你确认目标盘
     2. 备份该盘上原有的 BOOT.bin 到 PC（带时间戳）
     3. 把 E:\LDSDR_010\BOOT.bin 复制过去
     4. 读回校验头部魔数
#>

$ErrorActionPreference = 'Stop'
$Src   = 'E:\LDSDR_010\BOOT.bin'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$BakDir = "E:\LDSDR_010\sd_backup_$Stamp"

function Line { param($c = '-') Write-Host ($c * 68) }

Line '='
Write-Host '  写 SD 卡 BOOT.bin  --  IoT-NTN PL 转发器上电自启动'
Line '='
Write-Host ''

# ---------- 0. 检查源文件 ----------
if (-not (Test-Path -LiteralPath $Src)) {
    Write-Host "  [错误] 找不到 $Src" -ForegroundColor Red
    Write-Host "         请先运行 生成BOOT.bin.bat"
    Read-Host "`n按回车退出"; exit 1
}
$srcInfo = Get-Item -LiteralPath $Src
$b = [System.IO.File]::ReadAllBytes($Src)
$MAGIC = [Convert]::ToUInt32("AA995566", 16)
$magicOk = ($b.Length -gt 40) -and ([BitConverter]::ToUInt32($b, 32) -eq $MAGIC)
Write-Host ("  源文件 : {0}" -f $Src)
Write-Host ("  大小   : {0:N0} 字节" -f $srcInfo.Length)
Write-Host ("  时间   : {0}" -f $srcInfo.LastWriteTime)
if ($magicOk) {
    Write-Host "  头部   : AA995566  OK" -ForegroundColor Green
} else {
    Write-Host "  头部   : 魔数不对！这个文件不能用来启动" -ForegroundColor Red
    Read-Host "`n按回车退出"; exit 1
}
Write-Host ''

# ---------- 1. 找可移动磁盘 ----------
Line
Write-Host '  检测到的可移动磁盘：'
Line
$vols = Get-Volume | Where-Object { $_.DriveType -eq 'Removable' -and $_.DriveLetter }
if (-not $vols) {
    Write-Host '  （没有检测到可移动磁盘，请先插好 SD 卡读卡器）' -ForegroundColor Yellow
    Read-Host "`n按回车退出"; exit 1
}
foreach ($v in $vols) {
    $root = "$($v.DriveLetter):\"
    $hasBoot = Test-Path -LiteralPath "$root\BOOT.bin"
    $hasUboot = Test-Path -LiteralPath "$root\u-boot.elf"
    $hasImg = Test-Path -LiteralPath "$root\image.ub"
    Write-Host ("    {0}  {1,-12} {2,-8} {3,8:N2} GB   {4}" -f `
        $root, $v.FileSystemLabel, $v.FileSystem,
        ($v.Size / 1GB),
        $(if ($hasBoot) { '[有 BOOT.bin]' } else { '' }) +
        $(if ($hasImg)  { ' [有 image.ub]' } else { '' }) +
        $(if ($hasUboot){ ' [有 u-boot.elf]' } else { '' }))
}
Write-Host ''

$def = if ($vols.Count -eq 1) { "$($vols[0].DriveLetter):" } else { $null }
$ans = Read-Host ("  请输入目标盘符" + $(if ($def) { "（直接回车 = $def）" } else { "（例如 E:）" }))
if ([string]::IsNullOrWhiteSpace($ans)) { $ans = $def }
if (-not $ans) { Write-Host '  未指定盘符，退出。' -ForegroundColor Yellow; exit 1 }
$drive = $ans.Trim().TrimEnd('\') 
if ($drive -notmatch '^[A-Za-z]:$') { $drive = $drive.Substring(0,1) + ':' }
if (-not (Test-Path -LiteralPath "$drive\")) {
    Write-Host "  [错误] $drive 不存在" -ForegroundColor Red
    Read-Host "`n按回车退出"; exit 1
}

# ---------- 2. 备份 ----------
Write-Host ''
Line
Write-Host '  1/3  备份原有文件'
Line
New-Item -ItemType Directory -Force -Path $BakDir | Out-Null
$backedUp = 0
foreach ($f in @('BOOT.bin', 'boot.bin', 'image.ub', 'u-boot.elf', 'system.dtb')) {
    $p = Join-Path "$drive\" $f
    if (Test-Path -LiteralPath $p) {
        Copy-Item -LiteralPath $p -Destination $BakDir -Force
        Write-Host ("    已备份 {0,-16} {1,12:N0} 字节" -f $f, (Get-Item -LiteralPath $p).Length)
        $backedUp++
    }
}
if ($backedUp -eq 0) {
    Write-Host '    （该盘上原有的启动文件不多，可能是空卡）'
}
Write-Host "    备份目录: $BakDir" -ForegroundColor Cyan

# ---------- 3. 写入 ----------
Write-Host ''
Line
Write-Host '  2/3  写入新 BOOT.bin'
Line
Copy-Item -LiteralPath $Src -Destination "$drive\BOOT.bin" -Force
Start-Sleep -Milliseconds 800
Write-Host ("    已写入 {0}\BOOT.bin" -f $drive)

# ---------- 4. 校验 ----------
Write-Host ''
Line
Write-Host '  3/3  读回校验'
Line
$chk = [System.IO.File]::ReadAllBytes("$drive\BOOT.bin")
$ok = ($chk.Length -eq $b.Length) -and ([BitConverter]::ToUInt32($chk, 32) -eq $MAGIC)
Write-Host ("    大小 {0:N0} / {1:N0}" -f $chk.Length, $b.Length)
Write-Host ("    头   {0:X8}" -f [BitConverter]::ToUInt32($chk, 32))
if ($ok) {
    Write-Host '    校验通过' -ForegroundColor Green
} else {
    Write-Host '    校验失败！请重新运行本脚本' -ForegroundColor Red
}

# ---------- 收尾 ----------
Write-Host ''
Line '='
Write-Host '  完成。接下来：'
Write-Host ''
Write-Host '    1. 安全弹出 SD 卡'
Write-Host '    2. 插回板子，上电'
Write-Host '    3. 打开串口终端 (115200 8N1) 观察 —— 会先看到 FSBL 的输出：'
Write-Host '         Xilinx First Stage Boot Loader'
Write-Host '         Boot mode is SD'
Write-Host '         Partition Number: 1 / 2 / 3'
Write-Host '       然后是我们的应用横幅：'
Write-Host '         ===== PL relay enabled ====='
Write-Host ''
Write-Host '    4. 看到横幅就说明成功 —— 之后板子完全独立，不需要电脑'
Write-Host ''
Write-Host ('  要恢复原厂固件：把 ' + $BakDir + ' 里的文件拷回 SD 卡即可')
Line '='
Write-Host ''
Read-Host '按回车退出'
