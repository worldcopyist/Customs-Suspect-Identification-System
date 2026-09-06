from fastapi import APIRouter
from app.api.v1.endpoints import persons, records
from app.api.v1.endpoints import community, system
from app.api.v1.endpoints import agents, assistant_events
from app.api.v1.endpoints import client_logs

from app.api.v1.endpoints import assistant, auth, camera, chat, detections, digital_human, health, media, operations, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(client_logs.router)
api_router.include_router(users.router)
api_router.include_router(media.router)
api_router.include_router(persons.router)
api_router.include_router(records.router)
api_router.include_router(detections.router)
api_router.include_router(camera.router)
api_router.include_router(chat.router)
api_router.include_router(chat.admin_router)
api_router.include_router(community.router)
api_router.include_router(system.router)
api_router.include_router(assistant.router)
api_router.include_router(agents.router)
api_router.include_router(assistant_events.router)
api_router.include_router(operations.router)
