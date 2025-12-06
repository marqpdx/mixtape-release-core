import time

from django.http import JsonResponse
# from langchain.memory import ConversationSummaryBufferMemory
from langchain_classic.memory import ConversationSummaryBufferMemory

# from llama_index.core import Settings
from rest_framework.views import APIView

from inkwell.config.ai_config import build_retriever, collection_name
from inkwell.config.custom_settings import Settings
from inkwell.models import LLMMessage as OurLLMMessage
from inkwell.scripts.utils import get_index, get_or_create_session


MAX_MEMORY_MESSAGES = 10
DEFAULT_COLLECTION = collection_name
MAX_CONTEXT_TOKENS = 1200
MAX_RESPONSE_TOKENS = 400
CONTEXT_WINDOW = 2048

PROMPT_TEMPLATE = (
    "You are a thoughtful assistant helping the user understand a complex concept.\n"
    "Base your answer only on the excerpts provided below.\n"
    "Use deep reasoning and synthesis. Write in natural, well-organized paragraphs.\n"
    "Do not copy text directly. Do not make up facts. If the answer is not in the excerpts, say: 'I don’t know.'\n\n"
    "Excerpts:\n{context}\n\n"
    "Question: {question}\n\n"
    "Answer:"
)

class SimpleRAGView(APIView):
    def post(self, request):

        # Parse request
        query = request.data.get("query", "").strip()
        session_id = request.data.get("session_id")
        session = get_or_create_session(session_id)

        if not query:
            return JsonResponse({"error": "Missing query"}, status=400)

        # Setup memory
        # Initialize memory with summary support
        memory = self._load_summary_memory(session)

        # Add user query to memory
        memory.chat_memory.add_user_message(query)

        # Retrieve context
        index = get_index(DEFAULT_COLLECTION)
        retriever = build_retriever(index, DEFAULT_COLLECTION)
        nodes = retriever.retrieve(query)

        # Limit by token budget
        selected_nodes, total_tokens = [], 0
        for n in nodes:
            text = n.node.text.strip()
            token_count = len(text.split())  # Approximate; consider using tokenizer
            if total_tokens + token_count > MAX_CONTEXT_TOKENS:
                break
            selected_nodes.append(text)
            total_tokens += token_count

        context = "\n\n".join(selected_nodes)
        final_prompt = PROMPT_TEMPLATE.format(context=context, question=query)

        logger.debug("Prompt token estimate: %s", len(final_prompt.split()))
        logger.debug("Final Prompt:\n%s", final_prompt)

        # Generate response
        try:
            start_time = time.time()
            response = Settings.llm.complete(
                final_prompt,
                temperature=0.3,
                max_tokens=MAX_RESPONSE_TOKENS,
                stop=["\nQ:", "\n\n"]
            )
            elapsed = time.time() - start_time
            logger.info("⏱️ Query took {elapsed:.2f} seconds")
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        ai_response = response.text.strip()
        md_response = response.text.strip().replace("\n\n", "\n\n")

        # Persist chat messages
        OurLLMMessage.objects.create(session=session, role="user", text=query)
        OurLLMMessage.objects.create(session=session, role="ai", text=ai_response)

        return JsonResponse({
            "query": query,
            "prompt": final_prompt,
            "response": ai_response,
            "md_response": md_response,
            "session_id": str(session.session_id),
        })

    def _load_summary_memory(self, session):
        history = OurLLMMessage.objects.filter(session=session).order_by("timestamp")
        memory = ConversationSummaryBufferMemory(
            llm=Settings.chat_llm,  # must support .complete or .predict()
            max_token_limit=MAX_CONTEXT_TOKENS,
            return_messages=True,
            buffer_summary=session.summary or ""
        )
        for msg in history:
            if msg.role == "user":
                memory.chat_memory.add_user_message(msg.text)
            elif msg.role == "ai":
                memory.chat_memory.add_ai_message(msg.text)
        return memory


