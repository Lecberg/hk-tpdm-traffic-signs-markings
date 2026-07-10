@echo off
title SVG to DXF Converter
cd /d "%~dp0"
echo Starting the SVG to DXF converter... your browser will open shortly.
python -m svg2dxf.webapp
pause
