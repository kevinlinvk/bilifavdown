# scheduler_job.py
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from bili_downloader import main  # 导入主程序

def job():
    """包装主程序为可调度任务"""
    try:
        logging.info("🏁 启动B站下载任务")
        main()
        logging.info("🎉 下载任务执行完成")
    except Exception as e:
        logging.error(f"🔥 任务执行失败: {str(e)}")

def run_scheduler():
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)-5s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 创建调度器（生产环境建议使用持久化存储）
    scheduler = BlockingScheduler(
        job_defaults={'max_instances': 1},
        timezone='Asia/Shanghai'
    )

    # 首次立即执行
    scheduler.add_job(
        job,
        'date',
        run_date=datetime.now(),
        id='initial_job'
    )

    # 周期任务配置
    scheduler.add_job(
        job,
        'interval',
        hours=6,  # 使用环境变量配置更灵活
        id='interval_job',
        coalesce=True,
        misfire_grace_time=300
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logging.info("🛑 接收到终止信号，正在关闭...")
    finally:
        scheduler.shutdown()

if __name__ == "__main__":
    run_scheduler()