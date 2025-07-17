import os
import uuid
import base64
import requests
from google.cloud import storage
from time import time

# --- 環境變數與設定 ---
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
GCS_PATH_PREFIX = 'predictions/kevin_model/'

# 設定 Google Cloud 認證
# 在 Cloud Run 環境中，認證會自動處理，不需要設定檔案路徑
# 只有在本地開發時才需要設定 GOOGLE_APPLICATION_CREDENTIALS
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if GOOGLE_APPLICATION_CREDENTIALS and not GOOGLE_APPLICATION_CREDENTIALS.startswith('{'):
    # 如果是檔案路徑（本地開發）
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
elif GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_APPLICATION_CREDENTIALS.startswith('{'):
    # 如果是 JSON 字串（Cloud Run 環境），寫入臨時檔案
    import tempfile
    import json
    try:
        # 驗證是否為有效的 JSON
        json.loads(GOOGLE_APPLICATION_CREDENTIALS)
        # 創建臨時檔案
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(GOOGLE_APPLICATION_CREDENTIALS)
            temp_cred_path = f.name
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_cred_path
        print(f"    - [Kevin模型] 已設定臨時認證檔案: {temp_cred_path}")
    except json.JSONDecodeError:
        print("    - [Kevin模型] 警告：GOOGLE_APPLICATION_CREDENTIALS 不是有效的 JSON")
# 在 Cloud Run 中，如果沒有設定 GOOGLE_APPLICATION_CREDENTIALS，會使用預設的服務帳戶
# 這是 kevin_api.py 中定義的 API 端點
KEVIN_API_URL = "https://detect-api-self.wenalyzer.xyz/detect"

def _upload_to_gcs(image_bytes, suffix='annotated.jpg'):
    """
    將圖片上傳到 GCS，使用 Signed URL 方式避免 ACL 問題
    """
    if not GCS_BUCKET_NAME:
        print("    - [Kevin模型] GCS_BUCKET_NAME 環境變數未設定，跳過圖片上傳")
        return None
    
    try:
        print(f"    - [Kevin模型] 開始上傳圖片到 GCS，大小: {len(image_bytes)} bytes")
        
        # 確保 image_bytes 是 bytes 類型
        if isinstance(image_bytes, str):
            image_bytes = image_bytes.encode('utf-8')
        
        # 初始化 Storage Client
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        
        filename = f"{GCS_PATH_PREFIX}{uuid.uuid4()}_{suffix}"
        blob = bucket.blob(filename)
        
        # 上傳檔案，不設定 ACL
        blob.upload_from_string(image_bytes, content_type='image/jpeg')
        
        # 直接使用公開 URL 格式，完全避開 ACL 檢查
        # 由於 Bucket 已設定 allUsers:objectViewer 權限，這個 URL 可以直接存取
        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        
        print(f"    - [Kevin模型] GCS 上傳成功，使用公開 URL")
        return public_url
        
    except Exception as e:
        print(f"    - [Kevin模型] GCS 上傳失敗: {e}")
        return None

def detect_pills(pil_image):
    """
    主要辨識函式，接收 PIL 圖片，呼叫 Kevin 的 API，並回傳標準化格式的結果。
    """
    start_time = time()
    print("    - [Kevin模型] 開始處理...")

    # 將 PIL Image 轉換回 bytes
    import io
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format='JPEG')
    image_bytes = img_byte_arr.getvalue()

    try:
        # 步驟 1: 呼叫 kevin_api.py 中定義的 API
        files = {"file": ("image.jpg", image_bytes, "image/jpeg")}
        print(f"    - [Kevin模型] 呼叫 API: {KEVIN_API_URL}")
        api_resp = requests.post(KEVIN_API_URL, files=files, timeout=30)
        api_resp.raise_for_status()
        result = api_resp.json()
        print(f"    - [Kevin模型] API 回應成功")
        
        # 調試：打印 API 回應內容（確保中文正確顯示）
        try:
            import json
            print(f"    - [Kevin模型] API 回應內容:")
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        except Exception as debug_e:
            print(f"    - [Kevin模型] API 回應內容顯示失敗: {debug_e}")
            print(f"    - [Kevin模型] API 回應原始內容: {repr(result)}")

        # 步驟 2: 解析 API 回應並標準化（適應新格式）
        if not result.get("success") or not result.get("data"):
            raise ValueError("API 回應格式不符或檢測失敗")

        data = result["data"]
        detections = data.get("detections", [])
        annotated_image_url = None

        # 處理標註後的圖片（新格式：data:image/jpeg;base64,xxx）
        annotated_image_base64 = data.get("annotated_image")
        if annotated_image_base64:
            print(f"    - [Kevin模型] 收到標註圖片，格式檢查...")
            # 新格式包含完整的 data URL，需要提取 base64 部分
            if annotated_image_base64.startswith("data:image/"):
                print(f"    - [Kevin模型] 檢測到 data URL 格式")
                # 分割 "data:image/jpeg;base64," 和實際的 base64 資料
                if "," in annotated_image_base64:
                    annotated_image_base64 = annotated_image_base64.split(',')[1]
                    print(f"    - [Kevin模型] 已提取 base64 部分，長度: {len(annotated_image_base64)}")
                else:
                    print(f"    - [Kevin模型] 警告：data URL 格式異常，沒有找到逗號分隔符")
            else:
                print(f"    - [Kevin模型] 直接 base64 格式，長度: {len(annotated_image_base64)}")
            
            try:
                # 清理 base64 字符串（移除可能的空白字符）
                annotated_image_base64 = annotated_image_base64.strip()
                print(f"    - [Kevin模型] 開始 Base64 解碼...")
                img_bytes_anno = base64.b64decode(annotated_image_base64)
                print(f"    - [Kevin模型] Base64 解碼成功，圖片大小: {len(img_bytes_anno)} bytes")
                
                annotated_image_url = _upload_to_gcs(img_bytes_anno)
                # 如果 GCS 上傳失敗，仍然繼續處理，只是沒有圖片 URL
                if not annotated_image_url:
                    print("    - [Kevin模型] GCS 上傳失敗，但繼續處理辨識結果")
            except Exception as decode_error:
                print(f"    - [Kevin模型] Base64 解碼失敗: {decode_error}")
                print(f"    - [Kevin模型] Base64 字符串前100字符: {annotated_image_base64[:100]}")
                print(f"    - [Kevin模型] Base64 字符串後100字符: {annotated_image_base64[-100:]}")
                annotated_image_url = None
        else:
            print(f"    - [Kevin模型] 沒有收到標註圖片")

        elapsed_time = time() - start_time
        
        # 記錄新格式的額外資訊
        total_detections = data.get("total_detections", len(detections))
        image_info = data.get("image_info", {})
        
        print(f"    - [Kevin模型] 檢測完成：找到 {total_detections} 個藥丸")
        if image_info:
            print(f"    - [Kevin模型] 圖片資訊：{image_info.get('original_size', 'Unknown')} {image_info.get('mode', '')}")
        
        # 調試：檢查 annotated_image_url 的狀態
        if annotated_image_url:
            print(f"    - [Kevin模型] 標註圖片上傳成功：{annotated_image_url}")
        else:
            print(f"    - [Kevin模型] 標註圖片上傳失敗或跳過")
        
        # 依照統一格式回傳結果
        return {
            'detections': detections,
            'elapsed_time': elapsed_time,
            'model_name': 'kevin模型',
            'annotated_image_url': annotated_image_url,
            'detection_mode': 'single', # 標記為單一模型結果
            'success': True,
            # 新增的欄位
            'total_detections': total_detections,
            'image_info': image_info,
            'api_message': result.get("message", "")
        }

    except requests.exceptions.RequestException as e:
        print(f"!!!!!! [API 呼叫錯誤] Kevin模型 API 呼叫失敗: {e} !!!!!!")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"!!!!!! [嚴重錯誤] Kevin模型處理時發生錯誤: {e} !!!!!!")
        return {"success": False, "error": str(e)}