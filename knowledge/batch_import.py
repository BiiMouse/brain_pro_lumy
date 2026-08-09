"""
自动化批量导入脚本

功能：
1. 从指定目录查找所有以"07_"开头的.md文件
2. 按顺序逐个上传到知识库系统
3. 每个文件间隔15分钟
4. 监控任务状态直到完成后再上传下一个
"""

import os
import time
import requests
from pathlib import Path
from datetime import datetime, timedelta
import logging

from knowledge.processor.import_process.base import setup_logging

# 配置日志
setup_logging()
logger = logging.getLogger(__name__)


class BatchImporter:
    def __init__(self,
                 file_dir: str,
                 original_dir: str,
                 api_base: str = "http://127.0.0.1:8000",
                 interval_minutes: int = 15):
        """
        初始化批量导入器

        Args:
            file_dir: 文件所在目录
            original_dir: 原始文件目录（与file_dir相同）
            api_base: API服务地址
            interval_minutes: 文件间隔时间（分钟）
        """
        self.file_dir = Path(file_dir)
        self.original_dir = original_dir
        self.api_base = api_base
        self.interval_minutes = interval_minutes
        self.interval_seconds = interval_minutes * 60
        self.logger = logger

        # 查找所有符合条件的文件
        self.files = self._find_files()

        self.logger.info(f"=" * 70)
        self.logger.info(f"批量导入工具")
        self.logger.info(f"=" * 70)
        self.logger.info(f"文件目录: {file_dir}")
        self.logger.info(f"原始目录: {original_dir}")
        self.logger.info(f"API地址: {api_base}")
        self.logger.info(f"间隔时间: {interval_minutes} 分钟")
        self.logger.info(f"找到文件: {len(self.files)} 个")
        self.logger.info(f"=" * 70)

    def _find_files(self):
        """查找所有以'07_'开头的.md文件"""
        files = []
        for file in sorted(self.file_dir.glob("07_*.md")):
            files.append(file)
        return files

    def upload_file(self, file_path: Path) -> str:
        """
        上传单个文件

        Args:
            file_path: 文件路径

        Returns:
            task_id: 任务ID
        """
        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始上传: {file_path.name}")
        self.logger.info(f"{'=' * 70}")

        # 准备上传数据
        files = {'file': open(file_path, 'rb')}
        data = {'original_dir': self.original_dir}

        try:
            # 调用上传API
            response = requests.post(
                f"{self.api_base}/upload",
                files=files,
                data=data,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                task_id = result.get('task_id')
                self.logger.info(f"上传成功！任务ID: {task_id}")
                return task_id
            else:
                self.logger.error(f"上传失败: HTTP {response.status_code}")
                self.logger.info(f"响应: {response.text}")
                return None

        except Exception as e:
            self.logger.error(f" 上传异常: {e}")
            return None
        finally:
            files['file'].close()

    def monitor_task(self, task_id: str, max_duration_seconds: int = 60):
        """
        监控任务状态（仅在后台监控，不阻塞）

        Args:
            task_id: 任务ID
            max_duration_seconds: 监控时长（秒），默认60秒
        """
        self.logger.info(f"\n任务 {task_id} 已提交，后台处理中...")

        # 仅在短时间内监控状态，然后返回
        start_time = time.time()
        last_status = ""

        while time.time() - start_time < max_duration_seconds:
            try:
                response = requests.get(
                    f"{self.api_base}/status/{task_id}",
                    timeout=5
                )

                if response.status_code == 200:
                    data = response.json()
                    status = data.get('status')
                    done_list = data.get('done_list', [])

                    # 状态变化时打印
                    if status != last_status:
                        self.logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 状态: {status}")
                        if done_list:
                            self.logger.info(f"  已完成节点: {', '.join(done_list[-2:])}")
                        last_status = status

                    # 如果快速完成了，打印消息
                    if status == 'completed':
                        self.logger.info(f" 任务 {task_id} 在倒计时期间已完成！")
                        break
                    elif status == 'failed':
                        self.logger.error(f" 任务 {task_id} 失败，但继续下一个文件")
                        break

                time.sleep(3)

            except Exception as e:
                # 静默处理错误，不阻塞倒计时
                time.sleep(3)

    def wait_interval(self, file_index: int, total_files: int, last_task_id: str = None):
        """
        智能等待：倒计时 + 完成检查

        Args:
            file_index: 当前文件索引
            total_files: 总文件数
            last_task_id: 上一个任务ID（用于检查是否完成）
        """
        if file_index >= total_files - 1:
            self.logger.info(f"\n这是最后一个文件，无需等待")
            return

        wait_time = self.interval_seconds
        end_time = datetime.now() + timedelta(seconds=wait_time)

        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f"开始 {self.interval_minutes} 分钟倒计时...")
        self.logger.info(f"下一个文件预计在: {end_time.strftime('%Y-%m-%d %H:%M:%S')} 上传")

        # 倒计时显示
        while wait_time > 0:
            mins, secs = divmod(wait_time, 60)
            time_str = f"{int(mins):02d}:{int(secs):02d}"
            self.logger.info(f"\r 倒计时: {time_str}  ", end='', flush=True)
            time.sleep(10)
            wait_time -= 10

        self.logger.info(f"\n倒计时结束！")

        # 检查上一个任务是否完成
        if last_task_id:
            self.logger.info(f"\n 检查上一个任务状态...")
            completed = self._check_task_completion(last_task_id)

            if completed:
                self.logger.info(f"上一个任务已完成，准备上传下一个文件")
            else:
                self.logger.info(f"️  上一个任务仍在处理中...")
                self.logger.info(f" 策略：额外等待5分钟（最多）")

                # 额外等待最多5分钟
                extra_wait = 300  # 5分钟
                while extra_wait > 0:
                    mins, secs = divmod(extra_wait, 60)
                    time_str = f"{int(mins):02d}:{int(secs):02d}"
                    self.logger.info(f"\r 额外等待: {time_str}  ", end='', flush=True)
                    time.sleep(10)
                    extra_wait -= 10

                    # 每30秒检查一次是否完成
                    if (300 - extra_wait) % 30 == 0:
                        if self._check_task_completion(last_task_id):
                            self.logger.info(f"\n 任务完成！停止额外等待")
                            break

                self.logger.info(f"\n→ 准备上传下一个文件")

    def _check_task_completion(self, task_id: str) -> bool:
        """
        检查任务是否完成

        Args:
            task_id: 任务ID

        Returns:
            是否完成
        """
        try:
            response = requests.get(
                f"{self.api_base}/status/{task_id}",
                timeout=5
            )

            if response.status_code == 200:
                data = response.json()
                status = data.get('status')
                return status == 'completed'
        except:
            pass

        return False

    def run(self):
        """执行批量导入（并行处理模式）"""
        if not self.files:
            self.logger.error(" 没有找到符合条件的文件")
            return

        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f"文件目录: {self.file_dir}")
        self.logger.info(f"原始目录: {self.original_dir}")
        self.logger.info(f" API地址: {self.api_base}")
        self.logger.info(f"️  间隔时间: {self.interval_minutes} 分钟/文件")
        self.logger.info(f" 找到文件: {len(self.files)} 个")
        self.logger.info(f"{'=' * 70}")
        self.logger.info(f"\n即将上传的文件列表:")
        for i, file in enumerate(self.files, 1):
            self.logger.info(f"  {i}. {file.name}")

        # 预估完成时间
        total_minutes = len(self.files) * self.interval_minutes
        end_time = datetime.now() + timedelta(minutes=total_minutes)
        self.logger.info(f"\n⏰ 预计完成时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # 确认开始
        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f" 智能批量导入模式说明:")
        self.logger.info(f"  - 每个{self.interval_minutes}分钟上传一个文件")
        self.logger.info(f"  - 倒计时结束后检查上一个任务是否完成")
        self.logger.info(f"  - 如果未完成，额外等待最多5分钟")
        self.logger.info(f"  - 多个文件可能同时在后台处理")
        self.logger.info(f"  - 提前完成的任务会立即继续下一个")
        self.logger.info(f"{'=' * 70}")
        confirm = input("\n确认开始批量导入？(yes/no): ").strip().lower()
        if confirm != 'yes':
            self.logger.error("error: 取消导入")
            return

        # 开始导入
        success_count = 0
        fail_count = 0
        start_time = datetime.now()
        last_task_id = None  # 记录上一个任务ID

        for i, file_path in enumerate(self.files):
            self.logger.info(f"\n{'#' * 70}")
            self.logger.info(f"# 进度: [{i+1}/{len(self.files)}] - {file_path.name}")
            self.logger.info(f"{'#' * 70}")

            # 上传文件
            task_id = self.upload_file(file_path)

            if not task_id:
                self.logger.info(f" 上传失败，跳过此文件")
                fail_count += 1
                last_task_id = None
                # 即使上传失败，也等待倒计时，保持节奏
                if i < len(self.files) - 1:
                    self.wait_interval(i, len(self.files), last_task_id)
                continue

            success_count += 1
            last_task_id = task_id  # 保存当前任务ID

            # 短暂监控（60秒），看看状态
            self.monitor_task(task_id, max_duration_seconds=60)

            self.logger.info(f" 文件 {file_path.name} 已提交，后台处理中...")

            # 立即开始倒计时（最后一个文件不需要等待）
            if i < len(self.files) - 1:
                self.wait_interval(i, len(self.files), last_task_id)

        # 打印总结
        end_time = datetime.now()
        duration = end_time - start_time

        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f"批量导入完成！")
        self.logger.info(f"{'=' * 70}")
        self.logger.info(f"总文件数: {len(self.files)}")
        self.logger.info(f"成功提交: {success_count}")
        self.logger.info(f"失败: {fail_count}")
        self.logger.info(f"开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"总耗时: {duration}")
        self.logger.info(f"{'=' * 70}")
        self.logger.info(f"\n 提示: 所有文件已提交，后台可能仍在处理")
        self.logger.info(f"   您可以通过API查询任务状态确认是否全部完成")


if __name__ == "__main__":
    # 配置参数
    FILE_DIR = r"D:\LLM学习资料\智库项目\尚硅谷大模型项目实战之掌柜智库实战\1.资料\教育\数据\项目文档\掌柜智库"
    ORIGINAL_DIR = r"D:\LLM学习资料\智库项目\尚硅谷大模型项目实战之掌柜智库实战\1.资料\教育\数据\项目文档\掌柜智库"
    API_BASE = "http://127.0.0.1:8000"
    INTERVAL_MINUTES = 15

    # 创建导入器并运行
    importer = BatchImporter(
        file_dir=FILE_DIR,
        original_dir=ORIGINAL_DIR,
        api_base=API_BASE,
        interval_minutes=INTERVAL_MINUTES
    )

    try:
        importer.run()
    except KeyboardInterrupt:
        print(f"\n\n 用户中断导入")
    except Exception as e:
        print(f"\n\n 发生错误: {e}")
        import traceback
        traceback.print_exc()
