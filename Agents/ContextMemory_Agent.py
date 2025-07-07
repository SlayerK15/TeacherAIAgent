import chromadb
from chromadb.config import Settings
from typing import Any, Optional

class ContextMemoryAgent:
    def __init__(self, collection_name="ait_teacher_memory"):
        self.client = chromadb.Client(Settings(
            persist_directory="./chroma_db"
        ))
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def save(self, key: str, value: Any):
        # Store as string (could use json.dumps for dicts/lists)
        self.collection.upsert(
            ids=[key],
            documents=[str(value)]
        )

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        results = self.collection.get(ids=[key])
        if results["documents"]:
            return results["documents"][0]
        return default

    def append_to_list(self, key: str, value: Any):
        # Retrieve existing list, append, and save back
        existing = self.get(key, default="[]")
        import json
        try:
            lst = json.loads(existing)
        except Exception:
            lst = []
        lst.append(value)
        self.save(key, json.dumps(lst))

    def clear(self):
        # Danger: deletes all memory for this collection
        self.client.delete_collection(name=self.collection.name)
        self.collection = self.client.get_or_create_collection(name=self.collection.name)
