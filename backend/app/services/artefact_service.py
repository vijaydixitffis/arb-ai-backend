from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import asyncio
import aiofiles
import PyPDF2
import docx
import pandas as pd
from io import BytesIO
import re
from app.db.artefact_models import Artefact, ArtefactChunk, KnowledgeBase
from app.core.database import get_db
from app.services.llm_service import llm_service
from app.core.config import settings
import os

class ArtefactService:
    """Service for handling artefact processing, chunking, and embedding"""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm_service = llm_service
        self.chunk_size = 1500  # Optimal for embedding models
        self.chunk_overlap = 200
    
    async def process_artefact(
        self, 
        review_id: str, 
        domain_slug: str, 
        artefact_name: str, 
        artefact_type: str, 
        filename: str, 
        file_content: bytes
    ) -> Artefact:
        """Process uploaded artefact: extract text, chunk, and store"""
        
        # Save artefact to database
        artefact = Artefact(
            review_id=review_id,
            domain_slug=domain_slug,
            artefact_name=artefact_name,
            artefact_type=artefact_type,
            filename=filename,
            file_type=self._get_file_type(filename),
            file_size_bytes=len(file_content),
            content=file_content
        )
        
        self.db.add(artefact)
        self.db.commit()
        self.db.refresh(artefact)
        
        # Extract text from file
        text_content = await self._extract_text(file_content, filename)
        
        # Chunk the text
        chunks = self._chunk_text(text_content)
        
        # Save chunks
        for i, chunk_text in enumerate(chunks):
            chunk = ArtefactChunk(
                artefact_id=artefact.id,
                review_id=review_id,
                filename=filename,
                chunk_index=i,
                chunk_text=chunk_text
            )
            self.db.add(chunk)
        
        self.db.commit()
        
        # Generate embeddings (when vector extension is available)
        # await self._generate_embeddings(artefact.id)
        
        return artefact
    
    async def _extract_text(self, file_content: bytes, filename: str) -> str:
        """Extract text from various file types"""
        file_type = self._get_file_type(filename)
        
        if file_type == "pdf":
            return await self._extract_from_pdf(file_content)
        elif file_type == "docx":
            return await self._extract_from_docx(file_content)
        elif file_type in ["xlsx", "xls"]:
            return await self._extract_from_excel(file_content)
        elif file_type == "txt":
            return file_content.decode('utf-8', errors='ignore')
        else:
            # Default: try to decode as text
            return file_content.decode('utf-8', errors='ignore')
    
    async def _extract_from_pdf(self, file_content: bytes) -> str:
        """Extract text from PDF"""
        pdf_stream = BytesIO(file_content)
        pdf_reader = PyPDF2.PdfReader(pdf_stream)
        
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        
        return self._clean_text(text)
    
    async def _extract_from_docx(self, file_content: bytes) -> str:
        """Extract text from DOCX"""
        docx_stream = BytesIO(file_content)
        doc = docx.Document(docx_stream)
        
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        
        return self._clean_text(text)
    
    async def _extract_from_excel(self, file_content: bytes) -> str:
        """Extract text from Excel"""
        excel_stream = BytesIO(file_content)
        
        text = ""
        try:
            # Try to read as Excel
            df = pd.read_excel(excel_stream, sheet_name=None)
            for sheet_name, sheet_df in df.items():
                text += f"Sheet: {sheet_name}\n"
                text += sheet_df.to_string() + "\n\n"
        except:
            # Fallback: try CSV
            try:
                df = pd.read_csv(excel_stream)
                text = df.to_string()
            except:
                text = file_content.decode('utf-8', errors='ignore')
        
        return self._clean_text(text)
    
    def _chunk_text(self, text: str) -> List[str]:
        """Split text into chunks with overlap"""
        if not text:
            return []
        
        # Split by paragraphs first
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = ""
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            # If adding this paragraph exceeds chunk size, start new chunk
            if len(current_chunk) + len(paragraph) > self.chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                # Start new chunk with overlap from previous chunk
                words = current_chunk.split()
                overlap_words = words[-self.chunk_overlap//10:] if len(words) > self.chunk_overlap//10 else words
                current_chunk = " ".join(overlap_words) + "\n\n" + paragraph
            else:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
        
        # Add final chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text"""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove special characters that might cause issues
        text = re.sub(r'[^\w\s\n\.\,\;\:\!\?\-\(\)]', '', text)
        return text.strip()
    
    def _get_file_type(self, filename: str) -> str:
        """Get file type from filename"""
        extension = filename.lower().split('.')[-1]
        type_mapping = {
            'pdf': 'pdf',
            'docx': 'docx',
            'doc': 'docx',
            'xlsx': 'xlsx',
            'xls': 'xlsx',
            'txt': 'txt',
            'csv': 'txt'
        }
        return type_mapping.get(extension, 'txt')
    
    async def get_relevant_chunks(
        self, 
        review_id: str, 
        domain_slug: Optional[str] = None,
        query_text: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get relevant chunks for a review/domain"""
        
        query = self.db.query(ArtefactChunk).join(Artefact).filter(
            ArtefactChunk.review_id == review_id,
            Artefact.is_active == True
        )
        
        if domain_slug:
            query = query.filter(Artefact.domain_slug == domain_slug)
        
        chunks = query.order_by(ArtefactChunk.chunk_index).limit(limit).all()
        
        return [
            {
                "id": chunk.id,
                "artefact_id": chunk.artefact_id,
                "filename": chunk.filename,
                "chunk_index": chunk.chunk_index,
                "chunk_text": chunk.chunk_text,
                "domain_slug": chunk.artefact.domain_slug if chunk.artefact else None
            }
            for chunk in chunks
        ]
    
    async def get_artefacts_by_review(self, review_id: str) -> List[Dict[str, Any]]:
        """Get all artefacts for a review"""
        artefacts = self.db.query(Artefact).filter(
            Artefact.review_id == review_id,
            Artefact.is_active == True
        ).all()
        
        return [
            {
                "id": str(artefact.id),
                "review_id": str(artefact.review_id),
                "domain_slug": artefact.domain_slug,
                "artefact_name": artefact.artefact_name,
                "artefact_type": artefact.artefact_type,
                "filename": artefact.filename,
                "file_type": artefact.file_type,
                "file_size_bytes": artefact.file_size_bytes,
                "uploaded_at": artefact.uploaded_at.isoformat() if artefact.uploaded_at else None,
                "is_active": artefact.is_active
            }
            for artefact in artefacts
        ]

    async def delete_artefact(self, artefact_id: str) -> bool:
        """Delete an artefact and its chunks"""
        # Delete associated chunks first
        self.db.query(ArtefactChunk).filter(
            ArtefactChunk.artefact_id == artefact_id
        ).delete()
        
        # Delete the artefact
        result = self.db.query(Artefact).filter(
            Artefact.id == artefact_id
        ).delete()
        
        self.db.commit()
        return result > 0
    
    async def _generate_embeddings(self, artefact_id: str):
        """Generate embeddings for chunks using configured LLM provider"""
        chunks = self.db.query(ArtefactChunk).filter(
            ArtefactChunk.artefact_id == artefact_id
        ).all()
        
        for chunk in chunks:
            try:
                embedding = await self.llm_service.generate_embedding(chunk.chunk_text)
                # Store embedding when vector extension is available
                # chunk.embedding = embedding
                self.db.commit()
            except Exception as e:
                print(f"Error generating embedding for chunk {chunk.id}: {e}")
                continue
    
    async def search_knowledge_base(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 5,
        max_total_chars: int = 12000,
    ) -> List[Dict[str, Any]]:
        """Search knowledge base for relevant content.

        Returns up to `limit` entries whose combined content stays within
        `max_total_chars` characters (~3,000 tokens at 4 chars/token).
        Entries are ranked by keyword relevance so the most useful ones are
        kept when the budget runs out.
        """
        kb_query = self.db.query(KnowledgeBase).filter(
            KnowledgeBase.is_active == True
        )
        if category:
            kb_query = kb_query.filter(KnowledgeBase.category == category)

        results = kb_query.all()

        # Keyword relevance scoring
        query_terms = [t for t in query.lower().split() if len(t) > 2]
        scored = []
        for r in results:
            content_lower = r.content.lower()
            title_lower   = r.title.lower()
            relevance = sum(
                content_lower.count(t) * 2 + title_lower.count(t) * 3
                for t in query_terms
            )
            scored.append((relevance, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Collect up to `limit` entries within the total character budget
        selected = []
        chars_used = 0
        for relevance, r in scored:
            if len(selected) >= limit:
                break
            content = r.content or ""
            if chars_used + len(content) > max_total_chars and selected:
                # Don't overflow the budget; skip large entries once budget is tight
                continue
            selected.append({
                "id":            r.id,
                "title":         r.title,
                "content":       content,
                "category":      r.category,
                "principle_id":  r.principle_id,
                "relevance_score": relevance,
            })
            chars_used += len(content)

        return selected
