"""
CÓC ĐI LÀM — Script Triển Khai Backend Lên Hugging Face Spaces (100% Miễn Phí)
"""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

import os
import sys
import io
from pathlib import Path
from huggingface_hub import HfApi, create_repo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def deploy(space_name: str = "coc-di-lam-backend", hf_token: str | None = None):
    token = hf_token or os.getenv("HF_TOKEN")
    if not token and len(sys.argv) > 1:
        token = sys.argv[1]

    if not token:
        print("=" * 60)
        print("❌ LỖI: Chưa có Hugging Face Token!")
        print("Vui lòng lấy Access Token (Role: Write) tại:")
        print("👉 https://huggingface.co/settings/tokens")
        print("Cách chạy: python tools/admin/deploy_to_hf.py <YOUR_HF_TOKEN>")
        print("=" * 60)
        return

    try:
        api = HfApi(token=token)
        user_info = api.whoami()
        username = user_info.get("name")
        repo_id = f"{username}/{space_name}"

        print("=" * 60)
        print(f"🐸 Đang khởi tạo Hugging Face Space: {repo_id}")
        print(f"   SDK: Docker (2 vCPU, 16GB RAM Miễn Phí)")
        print("=" * 60)

        # 1. Tạo Space nếu chưa có
        create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="docker",
            private=False,
            exist_ok=True,
            token=token,
        )

        # 2. Upload code lên Space (bỏ qua file weights nặng vì Space sẽ tự kéo trực tiếp từ HF hub nội bộ)
        backend_dir = _WORKSPACE / "backend"
        print("🚀 Đang đẩy mã nguồn backend lên Hugging Face Space...")

        api.upload_folder(
            folder_path=str(backend_dir),
            repo_id=repo_id,
            repo_type="space",
            token=token,
            ignore_patterns=[
                "models/laya/model.safetensors",
                "models/laya/.cache/**",
                "*.pt",
                "*.pyc",
                "__pycache__/**",
                ".env",
                ".git/**",
            ],
        )

        subdomain = repo_id.replace("/", "-").lower()
        public_url = f"https://{subdomain}.hf.space"
        ws_url = f"wss://{subdomain}.hf.space/ws/interview/YOUR_SESSION_ID"

        print("=" * 60)
        print("✅ TRIỂN KHAI THÀNH CÔNG LÊN HUGGING FACE SPACES!")
        print(f"🔗 Space Link: https://huggingface.co/spaces/{repo_id}")
        print(f"🌐 Public API URL: {public_url}")
        print(f"🔌 WebSocket URL: {ws_url}")
        print("=" * 60)
        print("💡 Cập nhật vào frontend/.env.local:")
        print(f"NEXT_PUBLIC_API_URL={public_url}")
        print("=" * 60)

    except Exception as e:
        print(f"❌ Triển khai thất bại: {e}")

if __name__ == "__main__":
    token_arg = sys.argv[1] if len(sys.argv) > 1 else None
    deploy(hf_token=token_arg)
