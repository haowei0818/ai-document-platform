import uuid

from .llm_service import LLMService


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


def get_chroma_collection():
    import chromadb
    from django.conf import settings

    if getattr(settings, 'TESTING', False):
        path = "./chroma_db_test"
    else:
        path = "./chroma_db"

    chroma_client = chromadb.PersistentClient(path=path)
    return chroma_client.get_or_create_collection(name="documents")


def process_document_for_rag(document, llm=None):
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
