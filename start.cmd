@echo off
setlocal
cd /d "%~dp0"
set "CODEBRIDGE_NODE=D:\Study\CodeSoft\nodejs\node.exe"
if not exist "%CODEBRIDGE_NODE%" set "CODEBRIDGE_NODE=node"
"%CODEBRIDGE_NODE%" "%~dp0scripts\start-dsh.mjs" %*
set "CODEBRIDGE_START_EXIT=%ERRORLEVEL%"
if not "%CODEBRIDGE_START_EXIT%"=="0" pause
exit /b %CODEBRIDGE_START_EXIT%
