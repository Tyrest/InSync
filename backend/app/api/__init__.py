from fastapi import APIRouter

from app.api import admin, auth, config_client, dashboard, library, platforms, playlists, setup, sync

api_router = APIRouter(prefix="/api")
api_router.include_router(config_client.router, tags=["config"])
api_router.include_router(setup.router, prefix="/setup", tags=["setup"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(platforms.router, prefix="/platforms", tags=["platforms"])
api_router.include_router(playlists.router, prefix="/playlists", tags=["playlists"])
api_router.include_router(library.router, prefix="/library", tags=["library"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
