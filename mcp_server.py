import os
import django

# 1. Django Environment Setup (Yeh pehle hona zaruri hai)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'prathamesp32_project.settings')
django.setup()

# 2. Django Models & FastMCP import
try:
    from core.models import SensorData
except ImportError:
    SensorData = None  # Agar SensorData model nahi hai toh error na aaye

from core.models import KnowledgeBase, Document, DocumentChunk
from fastmcp import FastMCP

# FastMCP setup
mcp = FastMCP("Pratham ESP32 & Knowledge Base Server")

# ==================== SENSOR TOOLS ====================
if SensorData:
    @mcp.tool()
    def get_latest_sensor_data(device_id: str) -> dict:
        """ESP32 device ka latest temperature aur humidity data fetch karta hai."""
        try:
            latest = SensorData.objects.filter(device_id=device_id).latest('timestamp')
            return {
                "device_id": latest.device_id,
                "temperature": latest.temperature,
                "humidity": latest.humidity,
                "timestamp": str(latest.timestamp)
            }
        except SensorData.DoesNotExist:
            return {"error": f"No data found for device: {device_id}"}


# ==================== KNOWLEDGE BASE & RAG TOOLS ====================

@mcp.tool()
def list_knowledge_bases() -> list:
    """Sari Knowledge Bases aur unke documents ki list return karta hai."""
    kbs = KnowledgeBase.objects.all().prefetch_related('documents')
    result = []
    for kb in kbs:
        docs = [{"id": d.id, "name": d.name, "size": d.file_size} for d in kb.documents.all()]
        result.append({
            "kb_id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "documents_count": len(docs),
            "documents": docs
        })
    return result


@mcp.tool()
def upload_document_to_kb(kb_id: int, name: str, content: str) -> dict:
    """Naya document Knowledge Base mein upload karta hai aur chunks mein divide karta hai."""
    try:
        kb = KnowledgeBase.objects.get(id=kb_id)
    except KnowledgeBase.DoesNotExist:
        return {"status": "error", "message": f"Knowledge Base with ID {kb_id} not found."}
    
    if not content:
        return {"status": "error", "message": "Content cannot be empty."}

    size_kb = f"{len(content.encode('utf-8')) / 1024:.2f} KB"
    
    # Document Create karein
    doc = Document.objects.create(
        knowledge_base=kb,
        name=name,
        content=content,
        file_size=size_kb,
        status="Parsed"
    )

    # Chunking (300 characters per chunk)
    chunk_size = 300
    chunks_created = 0
    for i in range(0, len(content), chunk_size):
        chunk_text = content[i:i+chunk_size]
        DocumentChunk.objects.create(
            document=doc,
            chunk_text=chunk_text,
            chunk_index=(i // chunk_size) + 1
        )
        chunks_created += 1

    return {
        "status": "success",
        "document_id": doc.id,
        "document_name": doc.name,
        "chunks_count": chunks_created,
        "message": "Document successfully uploaded and chunked!"
    }


@mcp.tool()
def search_knowledge_base_chunks(query: str) -> list:
    """Knowledge Base ke chunks mein query ke hisab se RAG search perform karta hai."""
    if not query:
        return []
        
    matching_chunks = DocumentChunk.objects.filter(chunk_text__icontains=query)[:10]
    results = []
    for chunk in matching_chunks:
        results.append({
            "document_name": chunk.document.name,
            "knowledge_base": chunk.document.knowledge_base.name,
            "chunk_index": chunk.chunk_index,
            "text": chunk.chunk_text
        })
    return results


# ==================== NEW CHUNK EDIT & DELETE TOOLS ====================

@mcp.tool()
def update_document_chunk(chunk_id: int, new_text: str) -> dict:
    """Existing Document Chunk ka text update karta hai."""
    try:
        chunk = DocumentChunk.objects.get(id=chunk_id)
        if not new_text.strip():
            return {"status": "error", "message": "Chunk text cannot be empty."}
        
        chunk.chunk_text = new_text
        chunk.save()
        return {
            "status": "success",
            "chunk_id": chunk.id,
            "message": "Chunk updated successfully via MCP!"
        }
    except DocumentChunk.DoesNotExist:
        return {"status": "error", "message": f"Chunk with ID {chunk_id} not found."}


@mcp.tool()
def delete_document_chunk(chunk_id: int) -> dict:
    """Kisi specific Document Chunk ko delete karta hai."""
    try:
        chunk = DocumentChunk.objects.get(id=chunk_id)
        chunk.delete()
        return {
            "status": "success",
            "chunk_id": chunk_id,
            "message": "Chunk deleted successfully via MCP!"
        }
    except DocumentChunk.DoesNotExist:
        return {"status": "error", "message": f"Chunk with ID {chunk_id} not found."}


if __name__ == "__main__":
    mcp.run()