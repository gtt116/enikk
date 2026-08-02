#!/usr/bin/env python3
"""Enikk CLI - 命令行工具"""
import argparse
import sys
from pathlib import Path
import requests


def get_enikk_home() -> Path:
    """获取 enikk 主目录"""
    if home := Path.home() / ".enikk":
        return home
    raise RuntimeError("无法找到 enikk 主目录")


def get_server_url() -> str:
    """从端口文件读取服务器 URL"""
    port_file = get_enikk_home() / "server.port"
    if not port_file.exists():
        raise RuntimeError(
            f"端口文件不存在: {port_file}\n"
            "请确保 enikk 服务正在运行"
        )
    
    port = port_file.read_text().strip()
    return f"http://127.0.0.1:{port}"


def cmd_status(args):
    """检查服务状态"""
    try:
        url = get_server_url()
        response = requests.get(f"{url}/health", timeout=2)
        if response.status_code == 200:
            print("✅ enikk 服务运行中")
            print(f"   URL: {url}")
            return 0
        else:
            print(f"⚠️  服务响应异常: {response.status_code}")
            return 1
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到 enikk 服务")
        print("   请确保服务正在运行: enikk")
        return 1
    except Exception as e:
        print(f"❌ 错误: {e}")
        return 1


def cmd_cron_list(args):
    """列出定时任务"""
    try:
        url = get_server_url()
        response = requests.get(f"{url}/api/cron/list", timeout=5)
        if response.status_code == 200:
            jobs = response.json().get("jobs", [])
            if not jobs:
                print("没有定时任务")
                return 0
            
            print(f"共 {len(jobs)} 个定时任务:\n")
            for job in jobs:
                status = "✅" if job.get("enabled") else "❌"
                print(f"{status} {job['id'][:8]}... | {job['name']}")
                print(f"   调度: {job['schedule']}")
                print(f"   下次运行: {job.get('next_run', 'N/A')}")
                print()
            return 0
        else:
            print(f"错误: {response.status_code}")
            return 1
    except Exception as e:
        print(f"错误: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Enikk CLI - 命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # status 命令
    status_parser = subparsers.add_parser("status", help="检查服务状态")
    status_parser.set_defaults(func=cmd_status)
    
    # cron 命令组
    cron_parser = subparsers.add_parser("cron", help="定时任务管理")
    cron_subparsers = cron_parser.add_subparsers(dest="cron_command")
    
    # cron list
    cron_list_parser = cron_subparsers.add_parser("list", help="列出所有定时任务")
    cron_list_parser.set_defaults(func=cmd_cron_list)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    if hasattr(args, "func"):
        return args.func(args)
    else:
        # 子命令没有指定具体操作
        if args.command == "cron":
            cron_parser.print_help()
        else:
            parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
