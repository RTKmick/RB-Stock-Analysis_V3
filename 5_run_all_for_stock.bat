@echo off
setlocal

rem Project root：本 bat 所在目錄即專案根目錄
set "ROOT=%~dp0"
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

if not exist "%ROOT%" (
    echo Project root "%ROOT%" not found.
    pause
    exit /b 1
)

cd /d "%ROOT%"
if errorlevel 1 (
    echo Failed to change directory to "%ROOT%".
    pause
    exit /b 1
)

rem Ensure venv exists; create if missing
if not exist "venv\Scripts\activate.bat" (
    echo Creating venv...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create venv. Please check Python installation.
        pause
        exit /b 1
    )
)

set "PYEXE=%ROOT%\venv\Scripts\python.exe"
"%PYEXE%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARN] venv 內 Python 路徑失效，常見於複製專案或 Python 已搬移，將重建 venv。
    echo Rebuilding venv using python on PATH ...
    python -m venv --clear venv
    if errorlevel 1 (
        echo Failed. 請安裝 Python 並確認在終端機執行 python --version 有反應。
        pause
        exit /b 1
    )
    set "PYEXE=%ROOT%\venv\Scripts\python.exe"
    echo Installing dependencies from requirements.txt - please wait ...
    "%PYEXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo pip install failed.
        pause
        exit /b 1
    )
)

call ".\venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate venv.
    pause
    exit /b 1
)

echo ================================
echo One-key pipeline for stock^(s^)
echo ================================
set "STOCK_IDS="
set /p STOCK_IDS=Enter stock id^(s^) or press Enter for all tracked ^> 
if "%STOCK_IDS%"=="" (
    set "STOCK_IDS=2454 2486 3035 2330 2603 3661 2345 6547"
)

set "DAYS="
set /p DAYS=Enter lookback trading days ^(default 60^) ^> 
if "%DAYS%"=="" (
    set "DAYS=60"
)

echo.
echo [1/6] Running scraper_chip.py for %STOCK_IDS% ^(days=%DAYS%^) ...
for %%S in (%STOCK_IDS%) do (
    echo --- Running scraper_chip.py for %%S ---
    "%PYEXE%" scraper_chip.py --stock_id %%S --days %DAYS%
    if errorlevel 1 (
        echo scraper_chip.py failed for %%S. Please check the error above.
        pause
        exit /b 1
    )
)

echo.
echo [2/6] Rebuilding data\manifest.json ...
"%PYEXE%" sub-py\build_manifest.py

echo.
echo [3/6] ^(skip^) backtest_signals_60d.py ...
echo       已略過本機回測 backtest_signals_60d.py ，如需回測請手動執行：
echo       python sub-py\backtest_signals_60d.py --stock_ids %STOCK_IDS% --days %DAYS% --horizons 5,10,20

echo.
echo [4/6] Running Phase 1 analysis ^(analyze_signal_vs_returns.py^) ...
"%PYEXE%" sub-py\analyze_signal_vs_returns.py
if errorlevel 1 (
    echo analyze_signal_vs_returns.py failed. Please check the error above.
    pause
    exit /b 1
)

echo.
echo [5/6] Running Phase 3 ML winrate ^(ml_signal_winrate.py, horizons 5,10,20^) ...
"%PYEXE%" sub-py\ml_signal_winrate.py --horizons 5,10,20
if errorlevel 1 (
    echo ml_signal_winrate.py failed. Install scikit-learn and joblib: pip install scikit-learn joblib
    pause
    exit /b 1
)

echo.
echo [6/8] Smoke check outputs ^(smoke_check_artifacts.py^) ...
"%PYEXE%" sub-py\smoke_check_artifacts.py
if errorlevel 1 (
    echo Smoke check failed. Please fix issues above before upload.
    pause
    exit /b 1
)

echo.
echo [7/8] Generating market_context.json ^(TWSE^) ...
"%PYEXE%" scripts\generate_market_context.py --keep-on-fail
if errorlevel 1 (
    echo generate_market_context.py failed. Check TWSE connectivity or use --keep-on-fail with existing JSON.
)

echo.
echo [Extra] Telegram daily report ^(optional: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env^) ...
"%PYEXE%" send_daily_report.py

echo.
echo [8/8] Optional: upload changes to GitHub ^(upl_rb.bat^)
choice /M "Run upl_rb.bat to commit/push now?"
if errorlevel 2 (
    echo Skipping upload. You can run upl_rb.bat later.
) else (
    call upl_rb.bat
)

echo.
echo All steps finished.
pause

endlocal

