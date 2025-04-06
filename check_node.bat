@echo off
echo Checking Node.js installation...
where node
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Node.js not found
) else (
    echo Node.js found
)

echo Checking npm installation...
where npm
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: npm not found
) else (
    echo npm found
)

echo Checking npx installation...
where npx
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: npx not found
) else (
    echo npx found
)

echo.
echo Press any key to continue...
pause > nul
