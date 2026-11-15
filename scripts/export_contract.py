"""Export the runtime Pydantic contract; never consumes model quota."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.api.app import app
Path('packages/contracts/openapi.json').write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2)+'\n')
print('OpenAPI contract exported.')
