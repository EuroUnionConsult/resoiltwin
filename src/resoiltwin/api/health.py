from fastapi import APIRouter

from resoiltwin.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "service": get_settings().app_name, "environment": get_settings().environment}
