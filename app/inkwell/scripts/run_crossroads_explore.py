# run_crossroads_explore.py

# sys.exit()

# from llama_index.core import VectorStoreIndex, Settings, StorageContext

# from llama_index.vector_stores.qdrant import QdrantVectorStore


# from llama_index.core.query_engine import RetrieverQueryEngine
# from llama_index.llms.llama_cpp import LlamaCPP
# from llama_index.core.prompts import PromptTemplate as LlamaPromptTemplate



# Get the absolute path to the current script (llama_qdrant_setup.py)
# SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# # Build the path to the model
# MODEL_PATH = os.path.join(SCRIPT_DIR, "..", "models", "phi-2.Q4_K_M.gguf")
# MODEL_PATH = os.path.normpath(MODEL_PATH)

# ingest_documents() <- this is done in startup.py via apps.py

logger.info("pre sys")

# sys.exit()


        # start = time.time()
        # logger.info("Running indexingStore blank...")


# start = time.time()
# logger.info("Running llmRetriever...")

# llm = LlamaCPP(
#     model_path=MODEL_PATH,
#     temperature=0.1,
#     max_new_tokens=128,
#     context_window=2048,
#     model_kwargs={
#         "n_gpu_layers": 20,
#         "n_batch": 128,          # Controls how many tokens are processed at once
#         "f16_kv": True,         # Use 16-bit KV cache if supported
#         "use_mlock": False,     # Disable to save RAM if you're tight
#         "n_threads": 4,         # Tune this to your CPU (often 4-8 for M1/M2)
#         "verbose": True
#     },
# )

# LLM generation took 12.77s
# LLM generation took 10.87s

# Settings.llm = llm





# print()
# print()

# start = time.time()
# retrieved_nodes = retriever.retrieve("What do we know about PTSD?")
# end = time.time()

# logger.info("Retrieved {len(retrieved_nodes)} nodes in {end - start:.2f}s")
# print(retrieved_nodes)

# print()
# print()




# # Build the prompt manually from retrieved nodes
# prompt = "[INST] Use the context below to answer the question.\n\nContext:\n...your chunks...\n\nQuestion: What do we know about PTSD? [/INST]"

# start = time.time()
# output = llm.complete(prompt=prompt)
# print(output.text)

# end = time.time()

# logger.info("LLM generation took {end - start:.2f}s")
# # print(output)

# # Token count for debug
# # for token in llm.stream(prompt):
# #     print(token, end="", flush=True)
# # # logger.info("Prompt token count: {len(tokens)}")

# # # Time the LLM generation
# # start = time()
# # outputs = model.generate(
# #     **tokenizer(prompt, return_tensors="pt"),
# #     max_new_tokens=128  # reduce this!
# # )
# # end = time()

# # logger.info("LLM generation took {end - start:.2f}s")
# # print(tokenizer.decode(outputs[0], skip_special_tokens=True))




# sys.exit()








# end = time.time()
# logger.info("llmRetriever completed in {end - start:.2f} seconds")
# # llmRetriever completed in 0.25 seconds
# print()


# query_wrapper = LlamaPromptTemplate("[INST] {query_str} [/INST]")
# # Build the query engine with your filtered retriever
# query_engine = RetrieverQueryEngine.from_args(
#     retriever=retriever,
#     query_wrapper_prompt=query_wrapper
# )


# start = time.time()
# logger.info("Running query...")

# response = query_engine.query("query: What do we know about ptsd?")

# end = time.time()
# logger.info("query completed in {end - start:.2f} seconds")

# # response = query_engine.query("query: What do we know about ptsd?")

# # response = query_engine.query("Say hello.")

# print()
# print()
# print()
# print('**response**', response)
# print()
# print()
# print(response.source_nodes)
# print()
# print()

# # print('**response**', response.text)
# logger.info('*** END ***')




# # 5️⃣ Query System
# def query_qdrant_system(query: str):
#     retriever = index.as_retriever()
#     results = retriever.retrieve(query)
#     return [r.text for r in results]

# def query_qdrant_system2(query: str):
#     retriever = index.as_retriever()
#     results = retriever.retrieve(query)
#     return [r.text for r in results]

# # Example Usage
# if __name__ == "__main__":
#     query = "What is in the documents?"
#     response = query_qdrant_system(query)
#     print("\n".join(response))
