@echo off
setlocal

echo Creating Python 3.11 virtual environment...
py -3.11 -m venv .venv
if errorlevel 1 goto :error

call .venv\Scripts\activate.bat

echo Updating pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :error

echo Installing Python packages...
pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Python dependencies installed successfully.
echo.
echo IMPORTANT:
echo FFmpeg must also be installed and ffmpeg.exe must be on PATH.
echo Test this in Command Prompt:
echo     ffmpeg -version
echo.
pause
exit /b 0

:error
echo.
echo Installation failed.
pause
exit /b 1
