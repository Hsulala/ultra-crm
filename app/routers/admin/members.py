from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, Member
from app.schemas.member import BindingCodeResponse, MemberCreateRequest, MemberResponse
from app.services.binding_service import generate_binding_code
from app.templating import templates

router = APIRouter(prefix="/admin/members", tags=["admin-members"])


@router.get("/page")
def members_page(
    request: Request,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    members = db.query(Member).order_by(Member.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "admin/members.html",
        {"current_user": admin, "active": "members", "members": members},
    )


@router.post("", response_model=MemberResponse)
def create_member(
    payload: MemberCreateRequest,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    if payload.role not in ("student", "coach"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role 必須是 student 或 coach")
    if db.query(Member).filter(Member.member_no == payload.member_no).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "會員編號已存在")

    member = Member(member_no=payload.member_no, name=payload.name, role=payload.role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.post("/{member_id}/binding-code", response_model=BindingCodeResponse)
def issue_binding_code(
    member_id: int,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到會員")

    return generate_binding_code(db, member_id=member_id, created_by_admin_id=admin.id)
