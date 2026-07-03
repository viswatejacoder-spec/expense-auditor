from pydantic import BaseModel, Field
from typing import Optional

class QueryRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Expense audit query in free text")

class QueryResponse(BaseModel):
    success: bool = True
    report: Optional[str] = None

class ErrorResponse(BaseModel):
    success: bool = False
    error: Optional[str] = None
    detail: Optional[str] = None
