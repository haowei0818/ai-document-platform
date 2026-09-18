from django.shortcuts import render
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Document
from .serializers import DocumentSerializer, DocumentAskSerializer
from rest_framework.permissions import IsAuthenticated
from .rag_utils import process_document_for_rag, get_gemini_client, get_chroma_collection


class DocumentUploadView(generics.CreateAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        instance = serializer.save(user=self.request.user)
        process_document_for_rag(instance)


class DocumentListView(generics.ListAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Document.objects.filter(user=self.request.user)


class DocumentDeleteView(generics.DestroyAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Document.objects.filter(user=self.request.user)


class DocumentAskView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DocumentAskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']

        client = get_gemini_client()
        collection = get_chroma_collection()

        query_result = client.models.embed_content(
            model='gemini-embedding-001',
            contents=question
        )
        results = collection.query(
            query_embeddings=[query_result.embeddings[0].values],
            n_results=3,
            where={'user_id': request.user.id}
        )

        retrieved_chunks = results['documents'][0]
        metadatas = results['metadatas'][0]

        if not retrieved_chunks:
            return Response({
                'answer': '目前找不到相關的文件內容，請確認是否已上傳相關文件。',
                'sources': []
            })

        context = '\n\n'.join(retrieved_chunks)
        prompt = f"""你是一個嚴謹的文件問答助理。請「只根據」以下提供的文件內容回答問題，絕對不要加入文件內容沒有提到的資訊，也不要根據你自己的知識、常識或推測做任何補充或延伸建議。

如果文件內容不足以回答問題，請直接回覆「文件中沒有提到相關資訊」，不要嘗試自行推論、舉例或給出一般性建議。

文件內容：
{context}

問題：{question}"""

        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt
        )

        sources = []
        seen_ids = set()
        for meta in metadatas:
            if meta['document_id'] not in seen_ids:
                sources.append({'document_id': meta['document_id'], 'title': meta['title']})
                seen_ids.add(meta['document_id'])

        return Response({
            'answer': response.text,
            'sources': sources
        })
