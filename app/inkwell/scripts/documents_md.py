# indexing.py

import re
import time

from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import TokenTextSplitter

from inkwell.config.ai_config import configure_embedding


# Load documents
# Perform chunking
# Generate embeddings

def ingest_documents():


    configure_embedding()

    # Load Local Embedding Model
    # Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en") # Change model as needed

    # we're doing this b/c our BAAI/bge-base-en model does better with "passage" prefix
    class PrefixedSplitter(TokenTextSplitter):
        def split_text(self, text: str):
            chunks = super().split_text(text)
            return [f"passage: {chunk}" for chunk in chunks]


    def extract_metadata(text):
        metadata = {}
        patterns = {
            "title": r"Title:\s*(.*?)(?:\s+Tags:|$)",
            "tags": r"Tags:\s*(.*?)(?:\s+Date:|$)",
            "date": r"Date:\s*(.*?)(?:\s+Authors:|$)",
            "authors": r"Authors:\s*(.*?)(?:\s+Wherein:|$)",
            "collection": r"Collection:\s*(.*?)(?:\s+###|$)"
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                metadata[key] = match.group(1).strip()
        return metadata

    start = time.time()
    logger.info("Running doc prep...")

    documents = SimpleDirectoryReader("./ai/files").load_data()
    splitter = PrefixedSplitter(chunk_size=512, chunk_overlap=50)

    all_nodes = []

    # Add metadata to each chunk (node)
    for doc in documents:
        doc_metadata = extract_metadata(doc.text)

        # Chunk the document
        nodes = splitter.get_nodes_from_documents([doc])

        # Add metadata to each chunk/node
        for node in nodes:
            node.metadata.update({
                "source": doc.metadata.get("file_name", "unknown"),
                "doc_type": "internal",
                "priority": 10,
                "section": "trauma overview",
                **doc_metadata  # Include extracted metadata like title/tags/date
            })
            all_nodes.append(node)
            # print('meta!', node.metadata)

    end = time.time()
    logger.info("Doc Prep completed in {end - start:.2f} seconds")
    # Doc Prep completed in 0.56 seconds
    pass  # Empty line removed

    # Store in vector DB
    logger.info("Chunking and indexing complete.")

    return all_nodes
