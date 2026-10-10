from functools import lru_cache

from backend.app.core.config import settings


@lru_cache(maxsize=1)
def local_model():
    import torch
    from transformers import AutoModel, AutoTokenizer

    torch.set_num_threads(4)
    cache = str(settings.storage / "model-cache" / "embeddings")
    kwargs = {"cache_dir": cache, "trust_remote_code": False, "local_files_only": True}
    try:
        tokenizer = AutoTokenizer.from_pretrained(settings.local_embedding_model, **kwargs)
        model = AutoModel.from_pretrained(
            settings.local_embedding_model, use_safetensors=True, **kwargs
        )
    except OSError:
        kwargs["local_files_only"] = False
        tokenizer = AutoTokenizer.from_pretrained(settings.local_embedding_model, **kwargs)
        model = AutoModel.from_pretrained(
            settings.local_embedding_model, use_safetensors=True, **kwargs
        )
    model.eval()
    return tokenizer, model


def encode(texts):
    import torch
    import torch.nn.functional as functional

    tokenizer, model = local_model()
    output = []
    for offset in range(0, len(texts), 32):
        encoded = tokenizer(
            texts[offset : offset + 32],
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        )
        with torch.inference_mode():
            tokens = model(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).expand(tokens.size()).float()
            pooled = (tokens * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            vectors = functional.normalize(pooled, p=2, dim=1)
            output.extend(vectors.tolist())
    return output


def embedding_identity():
    return (
        "local:" + settings.local_embedding_model
        if settings.embedding_provider == "local"
        else "provider:"
        + (
            settings.openai_embedding_model
            if settings.openai_api_key
            else settings.azure_embedding_deployment
        )
    )
