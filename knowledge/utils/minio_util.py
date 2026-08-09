import os
from minio import Minio
from minio.error import S3Error

# 获取minio客户端连接对象的方法
def get_minio_client():
    try:
        client = Minio(
            # MinIO 服务端点
            endpoint=os.getenv("MINIO_ENDPOINT"),
            # 用户名
            access_key=os.getenv("MINIO_ACCESS_KEY"),
            # 密码
            secret_key=os.getenv("MINIO_SECRET_KEY"),
            # 不支持https方式，也就是http访问
            secure=False,
        )

        # 获取配置的bucket名称
        bucket_name = os.getenv("MINIO_BUCKET_NAME")

        # 检查bucket是否存在，不存在则创建
        if not client.bucket_exists(bucket_name):
            print(f"Bucket '{bucket_name}' 不存在，正在创建...")
            client.make_bucket(bucket_name)
            print(f"Bucket '{bucket_name}' 创建成功")
        else:
            print(f"Bucket '{bucket_name}' 已存在")

        return client
    except S3Error as e:
        print(f"MinIO S3 错误: {e}")
        raise e
    except Exception as e:
        print(f"MinIO 连接错误: {e}")
        raise e

