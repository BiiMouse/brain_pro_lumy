# -*- coding: utf-8 -*-
"""
测试 BGE-M3 模型是否能正常加载
"""
import os
import sys

os.chdir(r"D:\AIpractise\shopkeer_brain\knowledge")
sys.path.insert(0, r"D:\AIpractise\shopkeer_brain\knowledge")

print("=" * 60)
print("Start testing BGE-M3 model loading")
print("=" * 60)

try:
    print("\n[1] Check model path...")
    # 直接使用路径，不从环境变量读取
    bge_path = r"D:\ai_models\bge_models\BAAI\bge-m3"
    print(f"   Model path: {bge_path}")
    print(f"   Path exists: {os.path.exists(bge_path)}")

    print("\n[2] Import dependencies...")
    from pymilvus.model.hybrid import BGEM3EmbeddingFunction
    print("   [OK] pymilvus imported successfully")

    print("\n[3] Load BGE-M3 model...")
    print("   This may take 1-2 minutes, please wait...")

    bge_m3 = BGEM3EmbeddingFunction(
        model_name=bge_path,
        device="cpu",
        use_fp16=False,
        return_colbert_vecs=False
    )
    print("   [OK] Model loaded successfully!")

    print("\n[4] Test encoding...")
    test_texts = ["This is a test text", "BGE-M3 model test"]
    result = bge_m3.encode_documents(test_texts)
    print(f"   [OK] Encoding successful!")
    print(f"   Dense vector dimension: {len(result['dense'][0])}")
    print(f"   Sparse vector type: {type(result['sparse'])}")

    print("\n" + "=" * 60)
    print("[SUCCESS] All tests passed! BGE-M3 model works normally")
    print("=" * 60)

except Exception as e:
    print("\n" + "=" * 60)
    print(f"[FAILED] Test failed: {e}")
    print("=" * 60)
    import traceback
    traceback.print_exc()
    sys.exit(1)
