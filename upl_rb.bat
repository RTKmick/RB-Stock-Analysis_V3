@echo off
setlocal EnableExtensions

rem ---------------------------------------------------------------------------
rem 上傳變更到 GitHub：遠端 rtkmick / 分支 main（RB-Stock-Analysis_V3）
rem 本檔須放在專案根目錄執行。
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "REMOTE=rtkmick"
set "BRANCH=main"

cd /d "%ROOT%"
if errorlevel 1 (
    echo Failed to cd to "%ROOT%".
    pause
    exit /b 1
)

if not exist "%ROOT%\.git" (
    echo Not a git repository: "%ROOT%"
    pause
    exit /b 1
)

git remote get-url %REMOTE% >nul 2>&1
if errorlevel 1 (
    echo Remote "%REMOTE%" is not configured. Add it with:
    echo   git remote add %REMOTE% https://github.com/RTKmick/RB-Stock-Analysis_V3.git
    pause
    exit /b 1
)

echo Preparing to push to %REMOTE% / %BRANCH% ...

rem Log（Bat 目錄已於 .gitignore 排除 Bat/Log.txt 類型時可視需要調整）
if not exist "%ROOT%\Bat" mkdir "%ROOT%\Bat"
echo %date% %time% - Run [upl_rb] push %REMOTE% %BRANCH% >> "%ROOT%\Bat\Log.txt"

git status
echo.
echo [upl_rb] Staging main sources (no venv / no .env)...
git add core sub-py templates ^
    index.html README.md requirements.txt ^
    scraper_chip.py rb_tv_app.py ^
    *.bat .gitignore Version.txt ^
    data\*.json data\*.html data\manifest.json 2>nul

git status

for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "CUR=%%i"
if "%CUR%"=="" set "CUR=%BRANCH%"

git commit -m "%date% %time% - auto upload (upl_rb)" 2>nul
if errorlevel 1 (
    echo No changes to commit, or commit failed ^(see above^).
) else (
    echo Commit created.
)

echo [upl_rb] Pull --rebase %REMOTE%/%BRANCH% ...
git pull --rebase --autostash %REMOTE% %BRANCH%
if errorlevel 1 (
    echo Pull failed. Resolve conflicts then retry.
    pause
    exit /b 1
)

echo [upl_rb] Push to %REMOTE% %BRANCH% ...
git push %REMOTE% %CUR%:%BRANCH%
if errorlevel 1 (
    echo Push failed. Check: git remote -v  and  git branch -vv
    pause
    exit /b 1
)

echo Upload complete.
pause

endlocal
