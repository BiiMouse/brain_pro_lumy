"""
删除Milvus集合脚本

用途：删除现有的chunks集合，以便系统重新创建支持动态字段的新集合
执行环境：需要配置好.env文件，包含Milvus连接信息
"""

from knowledge.utils.milvus_client_util import get_milvus_client
from knowledge.processor.import_process.config import get_config


def delete_chunks_collection():
    """删除chunks集合"""
    try:
        # 获取配置
        config = get_config()
        collection_name = config.chunks_collection

        print(f"目标集合名称: {collection_name}")
        print("=" * 60)

        # 获取Milvus客户端
        client = get_milvus_client()

        # 检查集合是否存在
        if client.has_collection(collection_name):
            print(f"⚠️  集合 '{collection_name}' 存在")

            # 确认删除
            response = input(f"确认删除集合 '{collection_name}'？(yes/no): ").strip().lower()

            if response == 'yes':
                print(f"\n正在删除集合: {collection_name}")
                client.drop_collection(collection_name)
                print(f"✅ 集合 '{collection_name}' 已成功删除")
                print("\n" + "=" * 60)
                print("下一步操作:")
                print("1. 重启上传服务（如果正在运行）")
                print("2. 重新上传文档，系统会自动创建新集合")
                print("   新集合将支持动态字段（enable_dynamic_field=True）")
                print("=" * 60)
            else:
                print("❌ 取消删除操作")
        else:
            print(f"✓ 集合 '{collection_name}' 不存在，无需删除")
            print("\n" + "=" * 60)
            print("可以直接上传文档，系统会自动创建新集合")
            print("=" * 60)

    except Exception as e:
        print(f"❌ 删除集合时出错: {e}")
        print("\n可能的原因:")
        print("1. Milvus服务未运行")
        print("2. .env配置文件中的Milvus连接信息有误")
        print("3. 网络连接问题")
        raise


if __name__ == "__main__":
    print("=" * 60)
    print("Milvus集合删除工具")
    print("=" * 60)
    delete_chunks_collection()
