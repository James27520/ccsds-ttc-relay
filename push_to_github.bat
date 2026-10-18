@echo off
rem ===========================================================================
rem  push_to_github.bat -- add remote and push this repo to GitHub
rem
rem  BEFORE RUNNING, create an EMPTY repository on GitHub:
rem     1. open https://github.com/new
rem     2. Repository name: ccsds-ttc-relay
rem     3. IMPORTANT: do NOT tick "Add a README file",
rem        "Add .gitignore" or "Choose a license"  (they already exist locally)
rem     4. click "Create repository"
rem     5. copy the repo URL, e.g.
rem          https://github.com/<your-account>/ccsds-ttc-relay.git
rem
rem  Then double-click this file and paste that URL when asked.
rem
rem  NOTE: keep this file PURE ASCII with CRLF line endings.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set GIT=git
where git >nul 2>nul
if errorlevel 1 (
    if exist "E:\tools\PortableGit\cmd\git.exe" set "GIT=E:\tools\PortableGit\cmd\git.exe"
    if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
)
"%GIT%" --version >nul 2>nul
if errorlevel 1 (
    echo [X] git not found. Please run init_git.bat first.
    pause
    exit /b 1
)

echo ===========================================================================
echo   Push to GitHub
echo ===========================================================================
echo.

rem ---- current remote ----
"%GIT%" remote get-url origin >nul 2>nul
if not errorlevel 1 (
    echo [i] existing remote:
    "%GIT%" remote get-url origin
    echo.
    set /p RECONF=    Replace it? [y/N]:
    if /i not "!RECONF!"=="y" goto :dopush
    "%GIT%" remote remove origin
)

echo Paste the repository URL shown on GitHub, then press Enter.
echo   example:  https://github.com/yourname/ccsds-ttc-relay.git
echo.
set /p REPOURL=    URL:
if "!REPOURL!"=="" (
    echo [X] empty URL
    pause
    exit /b 1
)
"%GIT%" remote add origin "!REPOURL!"
if errorlevel 1 (
    echo [X] failed to add remote
    pause
    exit /b 1
)
echo.

:dopush
echo ---------------------------------------------------------------------------
echo   Pushing... a browser window may open for GitHub sign-in.
echo   That is Git Credential Manager asking for permission - approve it.
echo ---------------------------------------------------------------------------
echo.
"%GIT%" push -u origin main
if errorlevel 1 (
    echo.
    echo [X] push failed. Common causes:
    echo     - the GitHub repository was not created yet
    echo     - the URL has a typo
    echo     - you declined the browser sign-in
    echo.
    echo   To retry:
    echo     git push -u origin main
    echo   To check the remote:
    echo     git remote -v
    pause
    exit /b 1
)

echo.
echo ===========================================================================
echo   Done. Repository published.
echo ===========================================================================
"%GIT%" remote -v
echo.
"%GIT%" log --oneline -3
echo.
echo Open your repository in the browser:
echo   !REPOURL!
echo.
pause
endlocal
