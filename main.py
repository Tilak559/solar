from backend.routers.solar import solar
import fastapi

app = fastapi.FastAPI()

app.include_router(solar)

