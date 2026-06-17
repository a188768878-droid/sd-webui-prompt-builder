@echo off
setlocal enabledelayedexpansion
title AI Worker Node - %COMPUTERNAME%

:: Core Optimization for PyTorch VRAM
set PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.8,max_split_size_mb:512

:: Git Path Fix
set "CURRENT_DIR=%~dp0"
set "PATH=%CURRENT_DIR%git\bin;%CURRENT_DIR%git\cmd;%PATH%"

color 0A

:loop
cls
echo ======================================================
echo [%time%] Starting Distributed AI Cluster...
echo ======================================================

:: Kill ghost processes
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: Clear history input images to save disk space
del /q .\ComfyUI\input\*.* >nul 2>&1

:: Start ComfyUI Engine and redirect logs
echo [%time%] Waking up ComfyUI core...
start "ComfyUI_Engine" /b cmd /c ".\python\python.exe .\ComfyUI\main.py --listen 127.0.0.1 --port 8188 --preview-method auto > comfy_crash_log.txt 2>&1"

:: Warmup Delay
echo [%time%] Waiting 15 seconds for engine warmup...
timeout /t 15 /nobreak >nul

:: Start Worker Dispatcher
echo [%time%] Starting Worker Dispatcher...
".\python\python.exe" worker.py

:: Restart logic
echo.
echo ======================================================
echo [%time%] Worker exited! Restarting in 5 seconds...
echo ======================================================
timeout /t 5 /nobreak >nul
goto loop