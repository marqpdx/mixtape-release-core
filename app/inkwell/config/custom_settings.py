
class CustomSettings:
    def __init__(self):
        self.embed_model = None
        self.llm = None
        self.chat_llm = None
        self.tokenizer = None
        self.prompt_helper = None

    @staticmethod
    def get_chat_llm():
        return Settings.chat_llm  # assumes already set to ChatLlamaCpp

    @staticmethod
    def get_tokenizer():
        return Settings.tokenizer

    @staticmethod
    def get_prompt_helper():
        return Settings.prompt_helper

    @staticmethod
    def get_embed_model():
        return Settings.embed_model

# ✅ Export shared instance
Settings = CustomSettings()
