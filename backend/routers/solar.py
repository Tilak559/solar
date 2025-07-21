import pandas as pd
from fastapi import APIRouter
import requests
import numpy as np
import matplotlib.pyplot as plt
from ..services.solar import estimator

solar = APIRouter()

@solar.get("/measurements")
async def get_measurements(address: str):
    measurements = estimator(address)
    return measurements


