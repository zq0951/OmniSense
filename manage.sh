#!/bin/bash

# OmniSense SmartHome Management Script
# Designed for "Out-of-the-box" experience.

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

function log() {
    echo -e "${BLUE}[OmniSense]${NC} $1"
}

function error() {
    echo -e "${RED}[Error]${NC} $1"
}

function warn() {
    echo -e "${YELLOW}[Warn]${NC} $1"
}

# 1. 基础环境检查
log "正在检查环境..."

if [ ! -f .env ]; then
    warn "未找到 .env 文件。正在从 .env.example 创建..."
    if [ -f .env.example ]; then
        cp .env.example .env
        log "${GREEN}.env 文件已创建。${NC}请记得编辑 .env 并填入您的 HA_TOKEN 和其他配置。"
    else
        error "错误：未找到 .env.example。无法自动生成 .env。"
        exit 1
    fi
fi

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    error "未检测到 Docker，请先安装 Docker 和 Docker Compose。"
    exit 1
fi

function show_usage() {
    echo "用法: ./manage.sh [command] [options]"
    echo ""
    echo "命令:"
    echo "  start       启动 OmniSense 所有服务"
    echo "  stop        停止 OmniSense 服务"
    echo "  restart     重启 OmniSense 服务"
    echo "  logs        查看实时日志"
    echo "  clean       彻底清理容器、镜像和卷"
    echo "  help        显示帮助信息"
    echo ""
    echo "选项:"
    echo "  --build     启动前强制重新构建镜像"
}

case "$1" in
    start)
        DOCKER_CMD="docker compose"
        BUILD_FLAG=""
        
        [[ "$*" == *"--build"* ]] && BUILD_FLAG="--build"

        log "正在启动 OmniSense 服务..."
        
        $DOCKER_CMD up -d $BUILD_FLAG
        
        if [ $? -eq 0 ]; then
            log "✅ ${GREEN}OmniSense 启动成功！${NC}"
            log "您可以运行 ${BLUE}./manage.sh logs${NC} 查看系统运行状态。"
        else
            error "❌ 启动失败，请检查 Docker 日志或配置文件。"
        fi
        ;;

    stop)
        log "正在停止所有服务..."
        docker compose stop
        log "服务已停止。"
        ;;

    restart)
        log "正在重启..."
        $0 stop
        $0 start "${@:2}"
        ;;

    logs)
        log "正在查看日志 (Ctrl+C 退出)..."
        docker compose logs -f
        ;;

    clean)
        warn "⚠️ 警告：这将删除所有 OmniSense 容器、本地构建的镜像和持久化卷。"
        read -p "确定要继续吗？(y/N) " confirm
        if [[ "$confirm" == [yY] || "$confirm" == [yY][eE][sS] ]]; then
            docker compose down --rmi local --volumes --remove-orphans
            log "清理完成。"
        else
            log "已取消清理。"
        fi
        ;;

    help|*)
        show_usage
        ;;
esac
