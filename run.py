import os
import json
from dotenv import load_dotenv

# --- 核心修正 ---
# 在匯入任何我們自己的模組 (特別是 config) 之前，
# 就先執行 load_dotenv()。
# 這會讀取根目錄下的 .env 檔案，並將其內容載入到 os.environ 中。
load_dotenv()

# --- GCP 憑證處理 ---
# 如果 GCP_CREDENTIALS_BASE64 環境變數存在，解碼並寫入文件
import base64

gcp_credentials_base64 = os.environ.get('GCP_CREDENTIALS_BASE64')
gcp_credentials_json = os.environ.get('GCP_CREDENTIALS_JSON')

# 優先使用 base64 編碼的版本
if gcp_credentials_base64:
    try:
        print("🔍 使用 base64 編碼的 GCP 憑證")
        # 解碼 base64
        gcp_credentials_json = base64.b64decode(gcp_credentials_base64).decode('utf-8')
        print(f"✅ base64 解碼成功，JSON 長度: {len(gcp_credentials_json)}")
    except Exception as e:
        print(f"❌ base64 解碼失敗: {e}")
        gcp_credentials_json = None

if gcp_credentials_json:
    try:
        print(f"🔍 原始 GCP_CREDENTIALS_JSON 長度: {len(gcp_credentials_json)}")
        print(f"🔍 前100個字符: {gcp_credentials_json[:100]}")
        
        # 嘗試處理可能的轉義字符
        cleaned_json = gcp_credentials_json.strip()
        
        # 如果是被雙重轉義的字符串，嘗試解碼
        if cleaned_json.startswith('"') and cleaned_json.endswith('"'):
            cleaned_json = cleaned_json[1:-1]  # 移除外層引號
            cleaned_json = cleaned_json.replace('\\"', '"')  # 處理轉義的引號
            cleaned_json = cleaned_json.replace('\\\\', '\\')  # 處理轉義的反斜線
        
        print(f"🔍 清理後的 JSON 前100個字符: {cleaned_json[:100]}")
        
        # 驗證 JSON 格式
        parsed_json = json.loads(cleaned_json)
        print(f"✅ JSON 解析成功，包含 {len(parsed_json)} 個鍵")
        
        # 寫入憑證文件
        credentials_path = '/app/gcp-credentials.json'
        with open(credentials_path, 'w') as f:
            f.write(cleaned_json)
        
        # 設定環境變數指向文件路徑
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
        print(f"✅ GCP 憑證文件已創建: {credentials_path}")
        
    except json.JSONDecodeError as e:
        print(f"⚠️ GCP_CREDENTIALS_JSON 不是有效的 JSON 格式: {e}")
        print(f"🔍 錯誤位置附近的內容: {gcp_credentials_json[max(0, e.pos-50):e.pos+50] if hasattr(e, 'pos') else '無法定位'}")
    except Exception as e:
        print(f"❌ 創建 GCP 憑證文件時發生錯誤: {e}")
# -----------------

# 現在，當 create_app 和 config.py 被執行時，os.environ 已經有值了
from app import create_app

# 建立 Flask app 實例
# 我們在 create_app 中傳入設定類別的路徑字串
app = create_app('config.Config')

# 添加健康檢查端點
@app.route('/health')
def health_check():
    """健康檢查端點，用於 Docker 容器和負載均衡器"""
    return {
        'status': 'healthy',
        'timestamp': os.environ.get('TIMESTAMP', 'unknown'),
        'version': '1.0.0'
    }, 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    # 在 Cloud Run 環境中不啟動背景排程器
    # 改用 Google Cloud Scheduler 調用 HTTP 端點
    is_cloud_run = os.environ.get('K_SERVICE') is not None
    
    if not is_cloud_run:
        # 僅在本地開發環境啟動背景排程器
        import threading
        from app.services.reminder_service import run_scheduler
        scheduler_thread = threading.Thread(target=run_scheduler, args=(app,), daemon=True)
        scheduler_thread.start()
        print("本地開發環境：背景排程器已啟動")
    else:
        print("Cloud Run 環境：使用 Cloud Scheduler 進行提醒調度")
    
    app.run(host='0.0.0.0', port=port, debug=not is_cloud_run, use_reloader=False)