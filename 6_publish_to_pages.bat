@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem ---------------------------------------------------------------------------
rem 觸發 GitHub Pages 重新部署：推送到 RTKmick/RB-Stock-Analysis_V3 的 main
rem （與 upl_rb.bat 相同遠端；本檔須放在專案根目錄執行。）
rem 已停用：runbordev111/RB-stock-analysis（舊倉庫已刪除，勿再 push origin）
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "REMOTE=rtkmick"
set "BRANCH=main"

cd /d "%ROOT%"
if errorlevel 1 (
    echo [錯誤] 無法切換到專案目錄 "%ROOT%".
    pause
    exit /b 1
)

if not exist "%ROOT%\.git" (
    echo [錯誤] 此目錄不是 git 儲存庫。
    pause
    exit /b 1
)

git remote get-url %REMOTE% >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 未設定遠端 %REMOTE%。請執行：
    echo   git remote add %REMOTE% https://github.com/RTKmick/RB-Stock-Analysis_V3.git
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "CUR=%%i"
if "%CUR%"=="" set "CUR=%BRANCH%"

echo.
echo ==========================================
echo  Publish to GitHub Pages（%REMOTE% / %BRANCH%^）
echo  目前分支：%CUR%  ^>^>  遠端 %REMOTE%/%BRANCH%
echo ==========================================
echo.

echo [步驟] git push %REMOTE% %CUR%:%BRANCH% ...
git push %REMOTE% %CUR%:%BRANCH%
if errorlevel 1 (
    echo.
    echo [錯誤] Push 失敗。請檢查：git status、git pull --rebase %REMOTE% %BRANCH%
    pause
    exit /b 1
)

echo.
echo 完成。GitHub Actions / Pages 通常會在數分鐘內更新。
echo 儀表板網址（倉庫 Settings → Pages 須為 main 根目錄）：
echo   https://rtkmick.github.io/RB-Stock-Analysis_V3/
echo.
pause

endlocal
