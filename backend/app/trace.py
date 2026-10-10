def public_trace(value):
    """Only public results; never persist model reasoning or credential fields."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        if value.get("type") == "reasoning":
            return {"type": "reasoning", "note": "Private model reasoning is not displayed"}
        return {
            k: ("[source image input]" if k == "image_url" else public_trace(v))
            for k, v in value.items()
            if k.lower() not in {"api_key", "authorization", "reasoning", "chain_of_thought"}
        }
    if isinstance(value, list):
        return [public_trace(v) for v in value]
    return value
