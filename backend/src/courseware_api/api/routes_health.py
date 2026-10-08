from fastapi import APIRouter

from courseware_core.models import Health

router = APIRouter()

SERVICE_VERSION = "0.1.0"


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", service="courseware-copilot", version=SERVICE_VERSION)
