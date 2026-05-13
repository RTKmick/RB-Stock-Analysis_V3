@echo off
setlocal EnableExtensions

rem ---------------------------------------------------------------------------
rem 從 GitHub 拉最新（與本檔同層 = 專案根目錄 RB-Stock-Analysis_V3）
rem 遠端：rtkmick  分支：main  倉庫：RTKmick/RB-Stock-Analysis_V3
rem 若尚未設定遠端： git remote add rtkmick https://github.com/RTKmick/RB-Stock-Analysis_V3.git
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
    echo Clone first:
    echo   git clone https://github.com/RTKmick/RB-Stock-Analysis_V3.git
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

echo [downl_rb] Fetch %REMOTE% / %BRANCH% ...
git fetch %REMOTE%

git rev-parse --verify %BRANCH% >nul 2>&1
if errorlevel 1 (
    echo Creating local branch %BRANCH% from %REMOTE%/%BRANCH%...
    git checkout -b %BRANCH% %REMOTE%/%BRANCH%
    if errorlevel 1 (
        echo checkout failed.
        pause
        exit /b 1
    )
) else (
    git checkout %BRANCH%
    if errorlevel 1 (
        echo checkout failed.
        pause
        exit /b 1
    )
)

echo [downl_rb] Pull --rebase %REMOTE%/%BRANCH% ...
git pull --rebase --autostash %REMOTE% %BRANCH%
if errorlevel 1 (
    echo Pull failed. Resolve conflicts then retry.
    pause
    exit /b 1
)

echo.
echo [downl_rb] Done. Current branch:
git branch --show-current
git status -sb
pause

endlocal
