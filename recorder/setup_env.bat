@echo off
REM Setup Python virtual environment and install dependencies (Windows)
REM Run this from the repository root: setup_env.bat

python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo NOTE: Install PyTorch separately to match your CUDA support.
echo Recommended CPU-only example:
echo   pip install torch --index-url https://download.pytorch.org/whl/cpu
echo For GPU/CUDA, visit: https://pytorch.org/get-started/locally/
echo.
echo If you plan to use Whisper with GPU, ensure CUDA toolkit and compatible torch are installed.
pause
