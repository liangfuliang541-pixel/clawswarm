@echo off
chcp 65001 >nul
echo ========================================
echo   ClawSwarm GitHub Push Script
echo ========================================
echo.

cd /d "%~dp0"

REM 检查 git 是否安装
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Git，请先安装 Git:
    echo https://git-scm.com/download/win
    pause
    exit /b 1
)

REM 初始化仓库（如尚未初始化）
if not exist ".git" (
    echo [1/4] 初始化 Git 仓库...
    git init
    if %errorlevel% neq 0 (
        echo [错误] git init 失败
        pause
        exit /b 1
    )
)

REM 配置用户（如未配置）
git config user.email "you@example.com" 2>nul
git config user.name "Your Name" 2>nul

REM 添加所有文件
echo [2/4] 添加文件到 Git...
git add -A

REM 输入提交信息
echo.
set /p commit_msg="请输入提交信息 (直接回车使用默认): "
if "%commit_msg%"=="" set commit_msg=ClawSwarm v0.1: Multi-Agent Orchestration Framework

echo [3/4] 提交代码...
git commit -m "%commit_msg%"

REM 创建 GitHub 仓库并推送
echo [4/4] 创建 GitHub 仓库并推送...
gh repo create clawswarm --public --source=. --push

if %errorlevel% neq 0 (
    echo.
    echo [提示] 如果上方命令失败，请手动执行:
    echo   gh repo create clawswarm --public
    echo   git push -u origin main
    pause
    exit /b 1
)

echo.
echo ========================================
echo   推送成功！
echo   仓库地址: https://github.com/liangfuliang541-pixel/clawswarm
echo ========================================
pause
