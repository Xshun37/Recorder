# ==============================
# 傻瓜式项目启动器 (UV)
# ==============================

# 进入项目目录（脚本所在目录）
Set-Location $PSScriptRoot

# Conda deactivate（如果有）
if (Get-Command conda -ErrorAction SilentlyContinue) {
    conda deactivate 2>$null
}

# 运行 UV
uv run main.py