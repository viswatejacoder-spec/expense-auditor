# Simple FastAPI wrapper for local ADK Expense Auditor
# This file removes all Vertex AI and Google Cloud dependencies.
# It serves the frontend UI and provides a /api/query endpoint that forwards
# the user message to the ADK app defined in `app.agent`.

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import the ADK application (App instance) defined in app.agent
from app.agent import app as adk_app

class QueryRequest(BaseModel):
    """Pydantic model for incoming query payload."""
    message: str


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    - Serves static files from the `frontend` directory at `/ui`.
    - Exposes a POST `/api/query` endpoint that calls the ADK workflow.
    - Enables CORS for local development.
    """
    app = FastAPI()

    # Mount the UI (frontend) directory
    app.mount(
        "/ui",
        StaticFiles(directory="frontend", html=True),
        name="ui",
    )

    # CORS middleware – allow any origin for development convenience
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/query")
    async def query_endpoint(payload: QueryRequest):
        """Receive a user message, run the ADK workflow, and return the report.
        Expected JSON body: {"message": "<user query>"}"""
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Missing 'message' in request body")
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        runner = Runner(app=adk_app, session_service=InMemorySessionService(), auto_create_session=True)
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
        report_parts: list[str] = []
        for event in runner.run(user_id="ui_user", session_id="ui_user", new_message=content):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        report_parts.append(part.text)
            elif hasattr(event, "output") and event.output:
                report_parts.append(str(event.output))
        report = "\n".join(report_parts).strip()
        return JSONResponse(content={"success": True, "report": report})
    
    return app

# Export the FastAPI instance for uvicorn
app = create_app()
