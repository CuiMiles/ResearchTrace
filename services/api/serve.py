import os
from pathlib import Path
import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2]/'.env')

if __name__=='__main__':
    uvicorn.run('services.api.app:app',host=os.getenv('RT_HOST','127.0.0.1'),port=int(os.getenv('RT_PORT','18970')),workers=1,log_level='info')
