import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

USER_ID = os.getenv("USER_ID", "alexey")

# Auth tokens (supports rotation without downtime)
# Backward compatible: ADMIN_TOKEN still works if ADMIN_TOKEN_CURRENT not set
ADMIN_TOKEN_CURRENT = os.getenv("ADMIN_TOKEN_CURRENT", os.getenv("ADMIN_TOKEN", ""))
ADMIN_TOKEN_NEXT = os.getenv("ADMIN_TOKEN_NEXT", "")
