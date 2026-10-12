import httpx
from fastapi import APIRouter, Depends, Request, Response

from app.core.http_client import get_http_client
from app.core.i18n import request_language
from app.modules.education.schemas import Applicant, EducationReport, build_report
from app.modules.education.service import analyse

router = APIRouter()


@router.post("/analyse", response_model=EducationReport)
async def analyse_applicant(
    applicant: Applicant,
    request: Request,
    response: Response,
    client: httpx.AsyncClient = Depends(get_http_client),
) -> EducationReport:
    # No database dependency, input/output persistence or payload logging.
    response.headers["Cache-Control"] = "no-store"
    language = request_language(request)
    model = await analyse(
        client, applicant, language, request_id=getattr(request.state, "request_id", "unknown")
    )
    return build_report(model, language, applicant)
