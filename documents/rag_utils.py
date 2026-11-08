import logging
import uuid

from .llm_service import LLMService
from .models import Document

logger = logging.getLogger(__name__)


def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def extract_text_from_file(file_path):
    if file_path.endswith('.txt'):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    elif file_path.endswith('.pdf'):
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text = ''
        for page in reader.pages:
            text += page.extract_text() or ''
        return text
    elif file_path.endswith('.docx'):
        from docx import Document as DocxDocument
        doc = DocxDocument(file_path)
        text = '\n'.join([para.text for para in doc.paragraphs])
        return text
    else:
        raise ValueError(f"不支援的檔案格式: {file_path}")


_chroma_client = None


def get_chroma_client():
    """取得共用的 Chroma 倉庫；第一次用到才建立（正式環境存在硬碟）。"""
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path="./chroma_db")
    return _chroma_client


def set_chroma_client(client):
    """替換 Chroma 倉庫，讓測試可以改用記憶體模式。"""
    global _chroma_client
    _chroma_client = client


def get_chroma_collection():
    return get_chroma_client().get_or_create_collection(name="documents")


def delete_document_chunks(document_id):
    """刪除某份文件在 Chroma 裡的全部 chunk；沒有 chunk 時什麼都不做。"""
    get_chroma_collection().delete(where={'document_id': document_id})


def process_document(document, llm=None):
    """處理一份文件：pending → 清舊 chunk → 建立 chunk → ready；失敗時清掉殘留並改成 failed。

    上傳和重新處理（T5）都走這個流程。任何錯誤都會被接住並寫進 log，不會往外丟。
    """
    document.status = Document.Status.PENDING
    document.save(update_fields=['status'])
    delete_document_chunks(document.id)  # 先清掉舊 chunk
    try:
        _index_chunks(document, llm)
        document.status = Document.Status.READY
    except Exception:
        # log 只記 document_id，不記文件內容
        logger.exception('document processing failed: document_id=%s', document.id)
        delete_document_chunks(document.id)  # 清掉處理到一半寫進去的 chunk
        document.status = Document.Status.FAILED
    document.save(update_fields=['status'])
    return document


def _index_chunks(document, llm=None):
    """讀檔 → 切段 → 向量化 → 寫入 Chroma（內部步驟，失敗會直接丟出錯誤）。"""
    llm = llm or LLMService()
    collection = get_chroma_collection()

    text = extract_text_from_file(document.file.path)
    chunks = chunk_text(text)

    for i, chunk in enumerate(chunks):
        embedding = llm.embed(chunk)
        unique_id = f"doc{document.id}_chunk{i}_{uuid.uuid4().hex[:8]}"
        collection.add(
            ids=[unique_id],
            embeddings=[embedding],
            documents=[chunk],
            metadatas=[{
                'user_id': document.user.id,
                'document_id': document.id,
                'title': document.title,
            }]
        )
