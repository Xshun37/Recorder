param(
    [switch]$Elevated
)

# ==============================
# Foolproof Installer (PowerShell)
# ==============================

Write-Host "====================================================="
Write-Host "这是一个“傻瓜式”静默安装脚本。"
Write-Host "运行此程序表示您信任此脚本将对您的计算机进行的操作。"
Write-Host
Write-Host "This is a `"foolproof`" installer script."
Write-Host "By running this program you acknowledge and trust the actions it will perform on your computer."
Write-Host "====================================================="
Write-Host

if (-not $Elevated) {
    $choice = Read-Host "是否继续安装? (Y/N)"
    if ($choice -notmatch '^[Yy]$') {
        Write-Host "已选择退出。"
        return
    }
}

# ==============================
# Auto elevate to Administrator
# ==============================
if (-not $Elevated) {
    $principal = New-Object Security.Principal.WindowsPrincipal `
        ([Security.Principal.WindowsIdentity]::GetCurrent())

    if (-not $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) {
        Write-Host "需要管理员权限，正在请求提升权限..."
        Start-Process powershell `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Elevated" `
            -Verb RunAs
        exit
    }
}

# ==============================
# Config
# ==============================
$url      = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
$zipPath = Join-Path $PSScriptRoot "download.zip"
$destDir = Join-Path $PSScriptRoot "extracted"

# ==============================
# Download
# ==============================
Write-Host
Write-Host "正在下载:"
Write-Host $url

try {
    Invoke-WebRequest -Uri $url -OutFile $zipPath -ErrorAction Stop
    Write-Host "下载完成: $zipPath"
}
catch {
    Write-Error "下载失败: $($_.Exception.Message)"
    return
}

# ==============================
# Extract
# ==============================
Write-Host
Write-Host "正在解压到:"
Write-Host $destDir

try {
    if (Test-Path $destDir) {
        Remove-Item $destDir -Recurse -Force
    }
    Expand-Archive $zipPath $destDir -Force
    Write-Host "解压完成"
}
catch {
    Write-Error "解压失败: $($_.Exception.Message)"
    return
}

# ==============================
# Find installer
# ==============================
$exe = $null

if ([Environment]::Is64BitOperatingSystem) {
    $exe = Get-ChildItem $destDir -Recurse -Filter "VBCABLE_Setup_x64.exe" `
        -ErrorAction SilentlyContinue | Select-Object -First 1
}

if (-not $exe) {
    $exe = Get-ChildItem $destDir -Recurse -Filter "VBCABLE_Setup.exe" `
        -ErrorAction SilentlyContinue | Select-Object -First 1
}

if (-not $exe) {
    Write-Warning "未找到安装程序，跳过运行。"
    return
}

# ==============================
# Silent install
# ==============================
Write-Host
Write-Host "找到安装程序:"
Write-Host $exe.FullName
Write-Host "开始静默安装（不会显示任何窗口，请稍候）..."

$process = Start-Process `
    -FilePath $exe.FullName `
    -ArgumentList "/S" `
    -Wait `
    -PassThru

# ==============================
# Result
# ==============================
Write-Host
if ($process.ExitCode -eq 0) {
    Write-Host "✔ 静默安装完成"
} else {
    Write-Warning "⚠ 安装程序返回非零退出码: $($process.ExitCode)"
    Write-Warning "可能需要手动运行安装程序"
}

# ==============================
# 4️⃣ 安装 UV（使用 winget） + 刷新 PATH
# ==============================
Write-Host "`n检测 UV 是否存在..."
$uvExe = Get-Command uv -ErrorAction SilentlyContinue

if ($uvExe) {
    Write-Host "✔ UV 已存在，跳过安装"
} else {
    Write-Host "UV 未检测到，使用 winget 安装..."
    try {
        winget install --id uv --silent --accept-source-agreements --accept-package-agreements
        Write-Host "✔ UV 安装完成"
    } catch {
        Write-Warning "⚠ 使用 winget 安装 UV 失败: $($_.Exception.Message)"
    }

    # 刷新当前 PowerShell PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine")
    Write-Host "✔ PATH 已刷新，可立即使用 uv 命令"
}

# ------------------------------
# 5️⃣ (可选) deactive conda
# ------------------------------
if (Get-Command conda -ErrorAction SilentlyContinue) {
    Write-Host "`n检测到 Conda 环境，正在退出当前环境..."
    conda deactivate 2>$null
}

# ------------------------------
# 6️⃣ 配置项目 Python 依赖（UV 环境 + 镜像源）
# ------------------------------
Write-Host "`n开始配置项目 Python 依赖..."
Push-Location $PSScriptRoot

# 检查 uv.lock 可选
if (Test-Path "uv.lock") {
    Write-Host "检测到 uv.lock 文件，使用 uv 安装依赖..."
    uv install
} else {
    Write-Warning "未找到 uv.lock，跳过 UV 项目依赖安装"
}

# 使用 uv 环境的 pip 安装 Python 依赖（国内镜像源）
if (Test-Path "requirements.txt") {
    Write-Host "使用 uv pip 安装 Python 依赖（国内镜像源）..."
    uv pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
}

Pop-Location
Write-Host "依赖安装完成！"

Pop-Location
Write-Host "`n✔ 项目环境配置完成！"