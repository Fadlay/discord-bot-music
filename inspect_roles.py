from google.genai import types
import pydantic

content = types.Content(role="user", parts=[])
print(f"Role: {content.role}")
print(f"Fields: {content.model_fields.keys()}")
