@echo off
cd /d "%~dp0"
echo ========================================
echo        Directory Tree Cleaner
echo ========================================
echo.

python _clean_tree.py --force %*

echo.
echo Press any key to exit...
pause >nul
