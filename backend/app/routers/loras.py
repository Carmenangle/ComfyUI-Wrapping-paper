from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_loras() -> dict[str, object]:
    return {"items": []}
