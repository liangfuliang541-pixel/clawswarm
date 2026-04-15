@echo off
REM ClawSwarm 一键推送脚本
REM 运行此脚本将项目推送到 GitHub

cd /d %~dp0

echo ========================================
echo   ClawSwarm GitHub Push Script
echo ========================================
echo.

REM 检查 git 是否安装
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 git，请先安装 Git: https://git-scm.com
    pause
    exit /b 1
)

REM 检查是否已初始化
if not exist ".git" (
    echo [1/5] 初始化 Git 仓库...
    git init
    git branch -m main
) else (
    echo [1/5] Git 仓库已初始化
)

REM 检查 .gitignore
if not exist ".gitignore" (
    echo [2/5] 创建 .gitignore...
    (
        echo __pycache__/
        echo *.pyc
        echo .env
        echo venv/
        echo node_modules/
        echo queue/
        echo in_progress/
        echo results/
        echo agents/
        echo *.log
    ) > .gitignore
)

echo [3/5] 添加文件...
git add -A

REM 检查是否有文件添加
git diff --cached --quiet
if %errorlevel% neq 0 (
    echo [4/5] 创建提交...
    git commit -m "Initial commit: ClawSwarm v0.1 - Multi-Agent Orchestration Framework
    
    Features:
    - Multi-node task queue system
    - Node heartbeat monitoring
    - Task lifecycle management
    - Basic audit logging
    - Bilingual documentation (EN/CN)
    - Open source ready (AGPLv3)"
) else (
    echo [4/5] 没有新文件需要提交
)

REM 检查远程仓库
git remote -v | findstr "origin" >nul
if %errorlevel% neq 0 (
    echo [5/5] 创建 GitHub 仓库...
    gh repo create clawswarm --public --source=. --description "Coordinate multiple AI Agents like a lobster swarm 🦞"
) else (
    echo [5/5] 远程仓库已存在
)

echo.
echo ========================================
echo   推送到 GitHub...
echo ========================================
git push -u origin main

echo.
echo ========================================
echo   完成！ 
echo ========================================
echo.
echo 请访问: https://github.com/liangfuliang541-pixel/clawswarm
echo 别忘了点个 ⭐ Star ！
echo.

pause
