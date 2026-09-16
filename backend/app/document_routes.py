"""Document library endpoints, independent of the PDF analysis pipeline."""

from fastapi import APIRouter, HTTPException, Query

from app.database import delete_document, delete_summary, get_document, list_documents

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("")
def documents(
    q: str = Query("", max_length=300),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_documents(q.strip(), limit, offset)


@router.get("/{document_id}")
def document_detail(document_id: int):
    document = get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return document


@router.delete("/{document_id}")
def remove_document(document_id: int):
    if not delete_document(document_id):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return {"deleted": True}


@router.delete("/{document_id}/summaries/{summary_id}")
def remove_summary(document_id: int, summary_id: int):
    if not delete_summary(document_id, summary_id):
        raise HTTPException(status_code=404, detail="요약을 찾을 수 없습니다.")
    return {"deleted": True}
