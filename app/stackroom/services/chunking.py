"""
Chunking service for Stackroom.

Converts artifacts (full documents) into searchable chunks.

Strategy: Paragraph-based chunking with sliding window
- Target: 300-500 tokens per chunk (~1200-2000 chars)
- Splits on paragraph boundaries
- Tracks source spans for highlighting
- Adds metadata for chunk classification (TOC, heading, body)
"""

import hashlib
import re
from typing import List, Dict, Any

from stackroom.models import Artifact, Chunk


def estimate_tokens(text: str) -> int:
    """
    Rough token estimate (GPT-style).
    Real tokenization would use tiktoken, but this is close enough.

    Approximation: 1 token ≈ 4 characters for English
    """
    return len(text) // 4


def classify_chunk_type(text: str) -> str:
    """
    Classify a chunk as 'toc', 'heading', or 'body' based on content patterns.

    TOC indicators:
    - Numbered lists (1. 2. 3.)
    - Question lists (multiple lines ending with ?)
    - Very short lines with minimal content

    Heading indicators:
    - Short text (<100 chars)
    - Title case or ALL CAPS
    - No punctuation at end, or ends with colon

    Body:
    - Everything else (default)

    Args:
        text: Chunk text to classify

    Returns:
        'toc', 'heading', or 'body'
    """
    text_stripped = text.strip()
    lines = [line.strip() for line in text_stripped.split('\n') if line.strip()]

    # Check for TOC patterns
    # Pattern 1: Multiple list items (numbered, bulleted, lettered)
    # Matches: "1." "13." "1)" "13)" "a)" "• " "- " "* "
    list_pattern = r'^(?:[\d]+[.)]|[a-zA-Z][.)]|[•\-*]\s)'
    list_lines = sum(1 for line in lines if re.match(list_pattern, line))
    if list_lines >= 3 and list_lines >= len(lines) * 0.5:  # Lowered from 0.6 to 0.5
        return 'toc'

    # Pattern 2: Multiple questions (lines ending with ?)
    question_lines = sum(1 for line in lines if line.endswith('?'))
    if question_lines >= 3 and question_lines >= len(lines) * 0.6:
        return 'toc'

    # Pattern 3: Very short chunk with list-like structure
    if len(text_stripped) < 200 and len(lines) >= 3:
        # Check if lines are short and uniform (like a list)
        avg_line_length = sum(len(line) for line in lines) / len(lines)
        if avg_line_length < 50:
            return 'toc'

    # Check for heading patterns
    if len(text_stripped) < 100 and len(lines) <= 2:
        # Short, 1-2 lines
        # Check for title case or all caps
        if text_stripped.isupper() or text_stripped.istitle():
            return 'heading'
        # Check for no ending punctuation or ends with colon
        if not text_stripped[-1] in '.!?' or text_stripped.endswith(':'):
            return 'heading'

    # Default: body text
    return 'body'


def group_list_items(lines: List[str]) -> List[str]:
    """
    Group consecutive list items into single blocks.

    Detects lists (numbered, bulleted, or Q&A format) and groups
    consecutive items together so they aren't split across chunks.

    Args:
        lines: List of text lines

    Returns:
        List of text blocks (some may contain multiple list items grouped)
    """
    list_pattern = r'^(?:[\d]+[.)]|[a-zA-Z][.)]|[•\-*]\s)'
    grouped = []
    current_list = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # Empty line - end current list if any
            if current_list:
                grouped.append('\n'.join(current_list))
                current_list = []
            continue

        # Check if this line is a list item
        is_list_item = bool(re.match(list_pattern, stripped))

        if is_list_item:
            # Add to current list
            current_list.append(line)
        else:
            # Not a list item
            if current_list:
                # End the current list and add it
                grouped.append('\n'.join(current_list))
                current_list = []
            # Add this line as standalone
            grouped.append(line)

    # Add any remaining list
    if current_list:
        grouped.append('\n'.join(current_list))

    return grouped


def chunk_artifact(
    artifact: Artifact,
    strategy: str = "paragraph",
    target_chunk_size: int = 400,  # target tokens
    max_chunk_size: int = 600,      # max tokens before force split
) -> List[Chunk]:
    """
    Chunk an artifact into searchable pieces.

    Args:
        artifact: Artifact to chunk
        strategy: Chunking strategy ("paragraph" or "fixed")
        target_chunk_size: Target tokens per chunk
        max_chunk_size: Maximum tokens before forcing a split

    Returns:
        List of created Chunk objects
    """
    text = artifact.text or ""

    if not text.strip():
        return []

    # Split into lines first
    lines = text.split('\n')

    # Group list items together
    paragraphs = group_list_items(lines)

    chunks: List[Dict[str, Any]] = []
    current_chunk = []
    current_tokens = 0
    current_start = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_tokens = estimate_tokens(para)

        # If adding this paragraph exceeds max, finalize current chunk
        if current_tokens + para_tokens > max_chunk_size and current_chunk:
            # Finalize current chunk
            chunk_text = '\n\n'.join(current_chunk)
            chunk_end = current_start + len(chunk_text)

            chunks.append({
                'text': chunk_text,
                'char_start': current_start,
                'char_end': chunk_end,
            })

            # Start new chunk
            current_chunk = [para]
            current_tokens = para_tokens
            current_start = chunk_end + 2  # +2 for \n\n separator

        # If this single paragraph is huge, split it by sentences
        elif para_tokens > max_chunk_size:
            # Finalize any pending chunk first
            if current_chunk:
                chunk_text = '\n\n'.join(current_chunk)
                chunk_end = current_start + len(chunk_text)
                chunks.append({
                    'text': chunk_text,
                    'char_start': current_start,
                    'char_end': chunk_end,
                })
                current_chunk = []
                current_tokens = 0
                current_start = chunk_end + 2

            # Split long paragraph by sentences
            sentences = re.split(r'([.!?]+\s+)', para)
            sentence_chunk = []
            sentence_tokens = 0
            sentence_start = current_start

            for sent in sentences:
                if not sent.strip():
                    continue
                sent_tokens = estimate_tokens(sent)

                if sentence_tokens + sent_tokens > max_chunk_size and sentence_chunk:
                    # Finalize sentence chunk
                    sent_text = ''.join(sentence_chunk)
                    sent_end = sentence_start + len(sent_text)
                    chunks.append({
                        'text': sent_text,
                        'char_start': sentence_start,
                        'char_end': sent_end,
                    })
                    sentence_chunk = [sent]
                    sentence_tokens = sent_tokens
                    sentence_start = sent_end
                else:
                    sentence_chunk.append(sent)
                    sentence_tokens += sent_tokens

            # Add remaining sentences
            if sentence_chunk:
                sent_text = ''.join(sentence_chunk)
                sent_end = sentence_start + len(sent_text)
                chunks.append({
                    'text': sent_text,
                    'char_start': sentence_start,
                    'char_end': sent_end,
                })
                current_start = sent_end

        # Add to current chunk
        else:
            current_chunk.append(para)
            current_tokens += para_tokens

            # If we've reached target size, finalize
            if current_tokens >= target_chunk_size:
                chunk_text = '\n\n'.join(current_chunk)
                chunk_end = current_start + len(chunk_text)
                chunks.append({
                    'text': chunk_text,
                    'char_start': current_start,
                    'char_end': chunk_end,
                })
                current_chunk = []
                current_tokens = 0
                current_start = chunk_end + 2

    # Add any remaining content
    if current_chunk:
        chunk_text = '\n\n'.join(current_chunk)
        chunk_end = current_start + len(chunk_text)
        chunks.append({
            'text': chunk_text,
            'char_start': current_start,
            'char_end': chunk_end,
        })

    # Create Chunk objects
    created_chunks = []
    for idx, chunk_data in enumerate(chunks):
        chunk_hash = hashlib.sha256(chunk_data['text'].encode('utf-8')).hexdigest()

        # Classify chunk type for search ranking
        chunk_type = classify_chunk_type(chunk_data['text'])

        chunk = Chunk.objects.create(
            artifact=artifact,
            chunk_strategy=strategy,
            text=chunk_data['text'],
            token_estimate=estimate_tokens(chunk_data['text']),
            order_index=idx,
            source_spans=[{
                'char_start': chunk_data['char_start'],
                'char_end': chunk_data['char_end'],
                'chunk_type': chunk_type,  # Add metadata for ranking
            }],
            hash_sha256=chunk_hash,
        )
        created_chunks.append(chunk)

    return created_chunks
