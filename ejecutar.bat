@echo off
rem Bike Stores - arranque en un clic (Windows).
rem Solo ASCII en este archivo; los mensajes con acentos los imprime bootstrap.py.
setlocal EnableExtensions
cd /d "%~dp0"
title Bike Stores

call :find_python
if not defined PY goto no_python

%PY% bootstrap.py %*
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Hubo un error durante el arranque. Revisa el mensaje de arriba y logs\ejecutar.log
pause
exit /b 1

:find_python
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto :eof
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=python"
goto :eof

:no_python
echo.
echo No se encontro Python 3.10 o superior.
where winget >nul 2>&1
if errorlevel 1 goto manual_python
choice /C SN /M "Instalar Python 3.12 ahora con winget"
if errorlevel 2 goto manual_python
winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
call :find_python
if defined PY (
    %PY% bootstrap.py %*
    if errorlevel 1 goto failed
    exit /b 0
)
echo.
echo Python se instalo. Cierra esta ventana y vuelve a hacer doble clic en ejecutar.bat
pause
exit /b 1

:manual_python
echo Descarga Python 3.12 desde https://www.python.org/downloads/
echo Durante la instalacion marca "Add python.exe to PATH" y vuelve a ejecutar este archivo.
pause
exit /b 1
