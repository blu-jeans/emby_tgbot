import os
import sys
import logging
import asyncio
import threading
import time

# 将当前目录加入 Python Path 以确保模块导入路径无误
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from app.database import init_db, get_setting
from app.web import app, set_bot_manager

# 配置日志输出格式，兼顾标准输出与每日回滚，并添加 1G 总体积上限限制
log_dir = 'data'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
log_path = os.path.join(log_dir, 'bot.log')

import glob
from logging.handlers import TimedRotatingFileHandler

class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """按天回滚，且自动清理老日志保证总大小不超过 1GB 的日志 Handler"""
    def __init__(self, filename, when='D', interval=1, encoding='utf-8'):
        # backupCount 设为 0，我们使用自定义的清理逻辑控制总体积
        super().__init__(filename, when=when, interval=interval, backupCount=0, encoding=encoding)

    def doRollover(self):
        super().doRollover()
        self.cleanup_old_logs()

    def cleanup_old_logs(self):
        try:
            max_bytes = 1024 * 1024 * 1024  # 1 GB
            log_directory = os.path.dirname(self.baseFilename)
            base_name = os.path.basename(self.baseFilename)
            
            # 搜索匹配如 bot.log* 的所有回滚日志文件
            log_files = glob.glob(os.path.join(log_directory, base_name + "*"))
            total_size = sum(os.path.getsize(f) for f in log_files if os.path.isfile(f))
            
            if total_size <= max_bytes:
                return
                
            # 按修改时间升序排列备份日志文件（最旧的排在前面）
            backup_files = [f for f in log_files if f != self.baseFilename and os.path.isfile(f)]
            backup_files.sort(key=os.path.getmtime)
            
            for f in backup_files:
                file_size = os.path.getsize(f)
                try:
                    os.remove(f)
                    total_size -= file_size
                    sys.stdout.write(f"Log Cleaner: Removed old log backup '{f}' ({file_size} bytes) to free up space.\n")
                    if total_size <= max_bytes:
                        break
                except Exception as e:
                    sys.stderr.write(f"Failed to delete old log file {f}: {e}\n")
        except Exception as e:
            sys.stderr.write(f"Error executing log cleanup: {e}\n")

file_handler = SafeTimedRotatingFileHandler(log_path, when='D', interval=1, encoding='utf-8')
stream_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        stream_handler,
        file_handler
    ]
)
logger = logging.getLogger("emby_tgbot.main")

class BotManager:
    """管理 Telegram Bot 的生命周期（包含在独立线程中动态启动/停用/重启）"""
    def __init__(self):
        self.thread = None
        self.loop = None
        self.application = None
        self.lock = threading.Lock()

    def is_running(self):
        """检查 Bot 是否正常运行中"""
        with self.lock:
            return (
                self.thread is not None 
                and self.thread.is_alive() 
                and self.application is not None 
                and self.application.running
            )

    def start(self):
        """开启 Bot 线程"""
        with self.lock:
            if self.thread and self.thread.is_alive():
                logger.info("Bot 线程已在运行中，无需重复启动。")
                return

            logger.info("正在创建并启动 Bot 子线程...")
            self.thread = threading.Thread(target=self._run_loop, name="TelegramBotThread", daemon=True)
            self.thread.start()

    def stop(self):
        """停止 Bot 运行并清理线程与事件循环"""
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                logger.info("Bot 已经处于停止状态。")
                return

            logger.info("正在请求停止 Telegram Bot...")

            # 1. 尝试安全关闭 application 和其内部的 updater
            if self.application and self.loop and self.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self._stop_application(), self.loop)
                try:
                    # 等待异步关闭完成，最多等待 10 秒
                    future.result(timeout=10)
                    logger.info("Bot 异步组件安全关闭完成。")
                except Exception as e:
                    logger.error(f"安全关闭 Bot 组件时发生异常: {e}")

            # 2. 停止事件循环本身
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
                logger.info("已向 Bot 事件循环发送停止信号。")

            # 3. 等待子线程退出
            self.thread.join(timeout=5)
            logger.info("Bot 子线程退出完毕。")

            # 4. 重置状态
            self.thread = None
            self.loop = None
            self.application = None

    def restart(self):
        """重启 Bot"""
        logger.info("--- 正在执行 Bot 重启流程 ---")
        self.stop()
        # 稍作等待以释放端口或连接
        time.sleep(1)
        self.start()

    def _run_loop(self):
        """Bot 线程主入口：创建独立的 asyncio 事件循环并启动 Bot 运行"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_bot())
        except Exception as e:
            logger.error(f"Bot 线程事件循环执行异常: {e}")
        finally:
            self.loop.close()
            logger.info("Bot 子线程事件循环已关闭。")

    async def _run_bot(self):
        """异步拉起 python-telegram-bot"""
        token = get_setting('tg_token')
        if not token:
            logger.warning("未配置 Telegram Bot Token (tg_token)。Bot 处于待命/休眠状态，请登录后台进行配置。")
            # 保持事件循环运行，直到被 stop() 强行终止，以防线程直接退出
            while self.loop.is_running():
                await asyncio.sleep(1)
            return

        try:
            from telegram.ext import ApplicationBuilder, CommandHandler
            from app.bot import createaccount, get_group_id

            # 构建 Application
            self.application = ApplicationBuilder().token(token).build()
            self.application.add_handler(CommandHandler("createaccount", createaccount))
            self.application.add_handler(CommandHandler("groupid", get_group_id))

            # 初始化并启动
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("🎉 Telegram Bot 成功启动并开始监听消息！")

            # 保持协程活跃，直到事件循环被外部终止
            while self.loop.is_running():
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"拉起 Telegram Bot 失败: {e}")
            # 等待事件循环被清理
            while self.loop.is_running():
                await asyncio.sleep(2)
        finally:
            await self._stop_application()

    async def _stop_application(self):
        """关闭 Application 所有异步组件的封装函数"""
        if not self.application:
            return
            
        try:
            # 停止 polling 接收
            if self.application.updater and self.application.updater.running:
                await self.application.updater.stop()
                logger.info("Telegram Updater 已停止轮询。")
                
            # 停止 Application
            if self.application.running:
                await self.application.stop()
                logger.info("Telegram Application 已停止运行。")
                
            # 销毁 Application 占用的资源
            await self.application.shutdown()
            logger.info("Telegram Application 销毁完成。")
        except Exception as e:
            logger.error(f"关闭 Telegram 实例时遇到错误: {e}")
        finally:
            self.application = None

def main():
    # 1. 初始化数据库
    logger.info("正在检查并初始化 SQLite 数据库...")
    init_db()

    # 2. 创建并注入 Bot 生命周期管理器
    manager = BotManager()
    set_bot_manager(manager)

    # 3. 启动 Bot 线程
    manager.start()

    # 4. 启动 Flask Web 管理服务
    # 使用 threaded=True 以保证 Flask 能并发处理 Web 请求而不会卡顿
    port = int(os.environ.get("WEB_PORT", 5000))
    logger.info(f"正在启动 Flask Web 管理页面，监听端口: {port}...")
    try:
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    finally:
        # Flask 停止后，确保子线程中的 Bot 也同步安全退出
        logger.info("Flask Web 服务退出，正在同步关闭 Bot 进程...")
        manager.stop()
        logger.info("程序完全退出。")

if __name__ == '__main__':
    main()
