import chromadb
from chromadb.config import Settings
from typing import Any, Optional
from Agents.Logger_Agent import get_current

class ContextMemoryAgent:
    def __init__(self, collection_name="ait_teacher_memory"):
        self.client = chromadb.Client(Settings(
            persist_directory="./chroma_db"
        ))
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def save(self, key: str, value: Any):
        log = get_current()
        if log: log.info("ContextMemory.save", key=key, value_len=len(str(value)))
        self.collection.upsert(
            ids=[key],
            documents=[str(value)]
        )

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        log = get_current()
        results = self.collection.get(ids=[key])
        if results["documents"]:
            if log: log.info("ContextMemory.get hit", key=key)
            return results["documents"][0]
        if log: log.info("ContextMemory.get miss", key=key)
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
